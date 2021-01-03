'''
Base code forked from https://github.com/shaoxiongji/federated-learning
'''
import matplotlib
# matplotlib.use('Agg')
import sys
sys.path.append("./../")
sys.path.append("./../../")
sys.path.append("./")

import os
import matplotlib.pyplot as plt
import copy
import numpy as np
import json
import argparse
from torchvision import datasets, transforms
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler

from utils.sampling import mnist_iid, mnist_noniid, mnist_noniid_cluster, cifar_iid, emnist_noniid_cluster
from utils.options import args_parser
from models.Update import LocalUpdate
import pickle
from clustering import clustering_single, clustering_seperate, clustering_perfect, clustering_umap, clustering_encoder, clustering_umap_central, clustering_sequential_encoder
from sklearn.cluster import KMeans
import itertools
import copy
import umap

from tqdm import tqdm

from manifold_approximation.models.convAE_128D import ConvAutoencoder
from manifold_approximation.encoder import Encoder
from manifold_approximation.sequential_encoder import Sequential_Encoder
from sympy.utilities.iterables import multiset_permutations
# ----------------------------------
# Reproducability
# ----------------------------------
torch.manual_seed(123)
np.random.seed(321)
umap_random_state=42

def gen_data(iid, dataset_type, num_users, cluster):
    # load dataset and split users
    if dataset_type == 'mnist':
        # trans_mnist = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
        trans_mnist = transforms.Compose([transforms.ToTensor()])
        dataset_train = datasets.MNIST('../data/mnist/', train=True, download=True, transform=trans_mnist)
        dataset_test = datasets.MNIST('../data/mnist/', train=False, download=True, transform=trans_mnist)
        # sample users
        if iid:
            dict_users = mnist_iid(dataset_train, num_users)
        else:
            dict_users = mnist_noniid_cluster(dataset_train, num_users, cluster)
    #
    elif dataset_type == 'EMNIST':
        dataset_train = datasets.EMNIST(root='../data', split=args.dataset_split, 
                                                train=True, download=True, 
                                                transform=transforms.Compose([
                                                lambda img: transforms.functional.rotate(img, -90),
                                                lambda img: transforms.functional.hflip(img),
                                                transforms.ToTensor()]))

        dataset_test = datasets.EMNIST(root='../data', split=args.dataset_split, 
                                                    train=False, download=True, 
                                                    transform= transforms.Compose([
                                                    lambda img: transforms.functional.rotate(img, -90),
                                                    lambda img: transforms.functional.hflip(img),
                                                    transforms.ToTensor()]))      
        if not iid:
            dict_users = emnist_noniid_cluster(dataset_train, num_users, cluster, 
                                               random_shuffle=True)
    #       
    elif dataset_type == 'cifar':
        trans_cifar = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
        dataset_train = datasets.CIFAR10('../data/cifar', train=True, download=True, transform=trans_cifar)
        dataset_test = datasets.CIFAR10('../data/cifar', train=False, download=True, transform=trans_cifar)
        if iid:
            dict_users = cifar_iid(dataset_train, num_users)
        else:
            exit('Error: only consider IID setting in CIFAR10')
    else:
        exit('Error: unrecognized dataset')

    return dataset_train, dataset_test, dict_users

def gen_model(dataset, dataset_train, num_users):
    img_size = dataset_train[0][0].shape

    # build model
    if args.model == 'cnn' and dataset == 'cifar':
        net_glob = CNNCifar(args=args).to(args.device)
    elif args.model == 'cnn' and dataset == 'mnist':
        net_glob = CNNMnist(args=args).to(args.device)
    elif args.model == 'mlp':
        len_in = 1
        for x in img_size:
            len_in *= x
        net_glob = MLP(dim_in=len_in, dim_hidden=200, dim_out=args.num_classes).to(args.device)
    else:
        exit('Error: unrecognized model')
    print(net_glob)
    net_glob.train()

    # copy weights
    w_glob = net_glob.state_dict()
    net_glob_list = [copy.deepcopy(net_glob) for i in range(num_users)]
    w_glob_list = [copy.deepcopy(w_glob) for i in range(num_users)]
    
    return net_glob, w_glob, net_glob_list, w_glob_list

def get_model_params_length(model):
    lst = [list(model[k].cpu().numpy().flatten()) for  k in model.keys()]
    flat_list = [item for sublist in lst for item in sublist]

    return len(flat_list)

def clustering_multi_center(num_users, w_locals, multi_center_initialization_flag, est_multi_center, args):
    model_params_length = get_model_params_length(w_locals[0])
    models_parameter_list = np.zeros((num_users, model_params_length))

    for i in range(num_users):
        model = w_locals[i]
        lst = [list(model[k].cpu().numpy().flatten()) for  k in model.keys()]
        flat_list = [item for sublist in lst for item in sublist]

        models_parameter_list[i] = np.array(flat_list).reshape(1,model_params_length)


    if multi_center_initialization_flag:                
        kmeans = KMeans(n_clusters=args.nr_of_clusters, n_init=20).fit(models_parameter_list)

    else:
        kmeans = KMeans(n_clusters=args.nr_of_clusters, init=est_multi_center, n_init=1).fit(models_parameter_list)#TODO: remove the best
    
    ind_center = kmeans.fit_predict(models_parameter_list)

    est_multi_center_new = kmeans.cluster_centers_  
    clustering_matrix = np.zeros((num_users, num_users))

    for ii in range(len(ind_center)):
        ind_inter_cluster = np.where(ind_center == ind_center[ii])[0]
        clustering_matrix[ii,ind_inter_cluster] = 1

    return clustering_matrix, est_multi_center_new

def FedMLAlgo(net_glob_list, w_glob_list, dataset_train, dict_users, num_users, clustering_matrix, multi_center_flag, dataset_test, cluster, cluster_length, outputFile):
    print('iteration,training_average_loss,training_accuracy,test_accuracy', file = outputFile)
    # training
    loss_train = []
    if multi_center_flag:
        multi_center_initialization_flag = True
        est_multi_center = []

    if args.all_clients: 
        print("Aggregation over all clients")
        w_locals = w_glob_list
    for iter in range(args.epochs):
        loss_locals = []
        if not args.all_clients:
            w_locals = []
        m = max(int(args.frac * num_users), 1)
        idxs_users = np.random.choice(range(num_users), m, replace=False)
        for idx in idxs_users:
            local = LocalUpdate(args=args, dataset=dataset_train, idxs=dict_users[idx])
            w, loss = local.train(net=copy.deepcopy(net_glob_list[idx]).to(args.device))
            if args.all_clients:
                w_locals[idx] = copy.deepcopy(w)
            else:
                w_locals.append(copy.deepcopy(w))
            loss_locals.append(copy.deepcopy(loss))
        # update global weights
        if multi_center_flag:
            clustering_matrix, est_multi_center = clustering_multi_center(num_users, w_locals, multi_center_initialization_flag, est_multi_center, args)
            multi_center_initialization_flag = False

            plt.figure()
            plt.imshow(clustering_matrix)
            plt.savefig(f'{args.results_root_dir}/Clustering/clust_multicenter_nr_users-{args.num_users}_nr_clusters_{args.nr_of_clusters}_ep_{args.epochs}_itr_-{iter}.png')
            plt.close()
        
        #print(clustering_matrix)
        w_glob_list = FedAvg(w_locals, clustering_matrix)

        # copy weight to net_glob
        for idx in np.arange(num_users): #TODO: fix this
            net_glob_list[idx] = copy.deepcopy(net_glob_list[0])
            net_glob_list[idx].load_state_dict(w_glob_list[idx])

        # print loss
        loss_avg = sum(loss_locals) / len(loss_locals)
        print(f'Round {iter}, Average loss {loss_avg}')
        print(f'{iter}, {loss_avg}, ', end = '', file = outputFile)
        loss_train.append(loss_avg)


        if args.change_dataset_flag == True:
            if iter == (args.change_dataset_epoch-1):
                #generate dict_users, num_users, clustering_matrix, multi_center_flag, dataset_test, cluster, cluster_length
                args.flag_with_overlap = True
                # setting the clustering format
                cluster, cluster_length = gen_cluster(args)

                dataset_train, dataset_test, dict_users = gen_data(args.iid, args.dataset, args.num_users, cluster)

                # clustering the clients
                clustering_matrix = extract_clustering(dict_users, dataset_train, cluster, args)
                pass

        if args.iter_to_iter_results == True:
            print(f'iteration under process: {iter}')
            #print(f'iteration under process: {iter}', file = outputFile)
            # testing: average over all clients
            evaluation_index_range = extract_evaluation_range(args)
            evaluate_performance(net_glob_list, dataset_train, dataset_test, cluster, cluster_length, evaluation_index_range, args, outputFile)
    
    if args.iter_to_iter_results == False:
        print(f'{iter}, {loss_avg}, ', end = '', file = outputFile)

    return loss_train, net_glob_list, clustering_matrix

def evaluate_performance(net_glob_list, dataset_train, dataset_test, cluster, cluster_length, evaluation_index_range, args, outputFile):
    # evaluate the performance of the models on train and test datasets
    acc_train_final = np.zeros(args.num_users)
    loss_train_final = np.zeros(args.num_users)
    acc_test_final = np.zeros(args.num_users)
    loss_test_final = np.zeros(args.num_users)

    for idx in evaluation_index_range:
        print("user under process: ", idx)
        acc_train_final[idx], loss_train_final[idx] = test_img_classes(net_glob_list[idx], dataset_train, cluster[idx//cluster_length], args)
        acc_test_final[idx], loss_test_final[idx] = test_img_classes(net_glob_list[idx], dataset_test, cluster[idx//cluster_length], args)

    print('Training accuracy: {:.2f}'.format(np.average(acc_train_final[evaluation_index_range])))
    print('Testing accuracy: {:.2f}'.format(np.average(acc_test_final[evaluation_index_range])))

    print('{:.2f}, '.format(np.average(acc_train_final[evaluation_index_range])), end = '', file = outputFile)
    print('{:.2f}'.format(np.average(acc_test_final[evaluation_index_range])), file = outputFile)

    return

def gen_cluster(args):
    # setting the clustering format
    if args.iid == True:
        nr_of_clusters = 1
    
        cluster_length = args.num_users // nr_of_clusters
        cluster = np.zeros((nr_of_clusters,10), dtype='int64')
        for i in range(nr_of_clusters):
            # TODO: should it be np.random.choice(10, 2, replace=False) for a fairer comparison?
            cluster[i] = np.random.choice(10, 10, replace=False)
    else:
        cluster_length = args.num_users // args.nr_of_clusters
        # generate cluster settings    
        if args.flag_with_overlap:
            cluster = np.zeros((args.nr_of_clusters, 3), dtype='int64')
            lst = np.random.choice(10, 10, replace=False)
            cluster[0] = lst[0:3]
            cluster[1] = lst[2:5]
            cluster[2] = lst[4:7]
            cluster[3] = lst[6:9]
            cluster[4] = [lst[-2], lst[-1], lst[0]]
        else:
            cluster = np.zeros((args.nr_of_clusters, 2), dtype='int64')
            cluster_array = np.random.choice(10, 10, replace=False)
            for i in range(args.nr_of_clusters):
                cluster[i] = cluster_array[i*2: i*2 + 2]

    return cluster, cluster_length

def extract_clustering(dict_users, dataset_train, cluster, args):

    if args.clustering_method == 'single':
        clustering_matrix = clustering_single(args.num_users)
    elif args.clustering_method == 'local':
        clustering_matrix = clustering_seperate(args.num_users)
    elif args.clustering_method == 'perfect':
        clustering_matrix = clustering_perfect(args.num_users, dict_users, dataset_train, cluster, args)
    elif args.clustering_method == 'umap':
        clustering_matrix, _, _ = clustering_umap(args.num_users, dict_users, dataset_train, args)
    elif args.clustering_method == 'encoder':
        clustering_matrix, _, _, _ =\
            clustering_encoder(args.num_users, dict_users, dataset_train, 
                               args.ae_model_name, args.model_root_dir, args.manifold_dim, args)
    elif args.clustering_method == 'sequential_encoder':
        clustering_matrix, _, _, _ =\
            clustering_sequential_encoder(args.num_users, dict_users, dataset_train, args.ae_model_name, 
                                        args.nr_epochs_sequential_training, args)
    elif args.clustering_method == 'umap_central':
        clustering_matrix, _, _, _ =\
            clustering_umap_central(args.num_users, dict_users, dataset_train, args.ae_model_name, 
                                        args.nr_epochs_sequential_training, args)
        plt.figure()
        plt.imshow(clustering_matrix)
        plt.savefig(f'{args.results_root_dir}/Clustering/clust_umapcentral_nr_users-{args.num_users}_nr_clusters_{args.nr_of_clusters}_ep_{args.epochs}.png')
        plt.close()
    
    return clustering_matrix

def extract_evaluation_range(args):
    if args.iid == True:
        evaluation_index_step = 1
        evaluation_index_max = 1
    elif args.clustering_method == 'single' and args.multi_center == False:
        evaluation_index_step = args.num_users // args.nr_of_clusters# clustering_length
        evaluation_index_max = args.num_users
    else:
        evaluation_index_step = 1
        evaluation_index_max = args.num_users

    evaluation_index_range = np.arange(0, evaluation_index_max, evaluation_index_step)

    return evaluation_index_range

def main(args):
    
    # ----------------------------------
    plt.close('all')
    
    # ----------------------------------
    # generate cluster settings    

    nr_of_clusters = 10
    cluster_length = args.num_users // nr_of_clusters
    cluster = np.zeros((nr_of_clusters, 2), dtype='int64')
    for i in range(nr_of_clusters):
        cluster[i] = np.random.choice(10, 2, replace=False)
        
    # cluster_array = np.random.choice(10, 10, replace=False)
    # for i in range(nr_of_clusters):
    #     cluster[i] = cluster_array[i*2: i*2 + 1]
    
    if args.dataset == 'EMNIST': 
        n_1 = 47 // (nr_of_clusters - 1)
        n_2 = 47 % n_1
        cluster = np.zeros((nr_of_clusters, n_1), dtype='int64')
        # cluster_array = np.random.choice(47, 47, replace=False)
        cluster_array = np.arange(47)
        for i in range(nr_of_clusters - 1):
            cluster[i] = cluster_array[i*n_1: i*n_1 + n_1]
        cluster[nr_of_clusters - 1][0:n_2] = cluster_array[-n_2:]  
    # ----------------------------------       
    manifold_dim = 2
    nr_epochs_sequential_training = 5
    encoding_method = 'umap'    # umap, encoder, sequential_encoder, umap_central
    
    # ----------------------------------       
    clustering_method = 'umap_central'    # umap, encoder, sequential_encoder, umap_central

    # ----------------------------------
    # generate clustered data
    dataset_train, dataset_test, dict_users = gen_data(args.iid, args.dataset, args.num_users, cluster)
    
    # ----------------------------------    
    #average over clients in a same cluster
    clustering_matrix = clustering_perfect(args.num_users, dict_users, dataset_train, args)
    
    if clustering_method == 'umap':
        clustering_matrix0, clustering_matrix0_soft, centers = clustering_umap(args.num_users, dict_users, dataset_train, args)
    elif clustering_method == 'encoder':
        clustering_matrix0, clustering_matrix0_soft, centers, embedding_matrix =\
            clustering_encoder(args.num_users, dict_users, dataset_train, 
                               args.ae_model_name, args.model_root_dir, args.manifold_dim, args)
    elif clustering_method == 'sequential_encoder':
        clustering_matrix0, clustering_matrix0_soft, centers, embedding_matrix =\
            clustering_sequential_encoder(args.num_users, dict_users, dataset_train, args.ae_model_name, 
                                        args.nr_epochs_sequential_training, args)
    elif clustering_method == 'umap_central':
        clustering_matrix0, clustering_matrix0_soft, centers, embedding_matrix =\
            clustering_umap_central(args.num_users, dict_users, dataset_train, args.ae_model_name, 
                                        args.nr_epochs_sequential_training, args)
    
    # ----------------------------------    
    # plot results
    plt.figure(1)
    plt.imshow(clustering_matrix,cmap=plt.cm.viridis)
    plt.savefig(f'{args.results_root_dir}/Clustering/clustMat_perfect_nrclust-{nr_of_clusters}_from-{args.pre_trained_dataset}_to-{args.dataset}.jpg')
    
    plt.figure(2)
    plt.imshow(clustering_matrix0,cmap=plt.cm.viridis)
    plt.savefig(f'{args.results_root_dir}/Clustering/clustMat_{clustering_method}_nrclust-{args.nr_of_clusters}_from-{args.pre_trained_dataset}_to-{args.dataset}.jpg')
    
    plt.figure(3)
    plt.imshow(-1*clustering_matrix0_soft,cmap=plt.cm.viridis)
    plt.savefig(f'{args.results_root_dir}/Clustering/softClustMat_{clustering_method}_nrclust-{args.nr_of_clusters}_from-{args.pre_trained_dataset}_to-{args.dataset}.jpg')
    
    nr_of_centers = 2*cluster_length
    colors = itertools.cycle(["r"] * nr_of_centers +["b"]*nr_of_centers+["g"]*nr_of_centers+["k"]*nr_of_centers+["y"]*nr_of_centers)
    plt.figure(4)
    for i in range(0,args.num_users):
        plt.scatter(centers[i][0][0],centers[i][0][1], color=next(colors))
        plt.scatter(centers[i][1][0],centers[i][1][1], color=next(colors))
    plt.savefig(f'{args.results_root_dir}/Clustering/centers_{clustering_method}_nrclust-{args.nr_of_clusters}_from-{args.pre_trained_dataset}_to-{args.dataset}.jpg')
    
    if clustering_method not in ['umap_central', 'umap']:
        plt.figure(5)
        nr_of_centers = len(dict_users[0])*cluster_length
        colors = itertools.cycle(["r"]*1 + ["b"]*1 + ["g"]*1 + ["k"]*1 + ["y"]*1)
        for i in range(args.nr_of_clusters):
            plt.scatter(embedding_matrix[i*nr_of_centers:(i+1)*nr_of_centers, 0], embedding_matrix[i*nr_of_centers:(i+1)*nr_of_centers:, 1], color=next(colors))
        plt.savefig(f'{args.results_root_dir}/Clustering/embeddingMat_{clustering_method}_nrclust-{args.nr_of_clusters}_from-{args.pre_trained_dataset}_to-{args.dataset}.jpg')
    plt.show()
    return

if __name__ == '__main__':
    # parse args
    args = args_parser()
    args.device = torch.device('cuda:{}'.format(args.gpu) if torch.cuda.is_available() and args.gpu != -1 else 'cpu')

    # ----------------------------------
    plt.close('all')
    entries = os.listdir(f'{args.config_root_dir}/')
    for entry in entries:
        if not entry.endswith(".json"):
            continue
        with open(f'{args.config_root_dir}/{entry}') as f:
            args = args_parser()
            args.device = torch.device('cuda:{}'.format(args.gpu) if torch.cuda.is_available() and args.gpu != -1 else 'cpu')
        
            config_file_name = entry
            print(f'working on the cofig file: {args.config_root_dir}/{entry}')
            parser = argparse.ArgumentParser()
            argparse_dict = vars(args)
            argparse_dict.update(json.load(f))

            t_args = argparse.Namespace()
            t_args.__dict__.update(argparse_dict)
            args = parser.parse_args(namespace=t_args)

            main(args)
