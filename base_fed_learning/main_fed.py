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
import torchvision
from base_fed_learning.utils.sampling import mnist_iid, mnist_noniid, mnist_noniid_cluster, cifar_iid
from base_fed_learning.utils.options import args_parser
from base_fed_learning.models.Update import LocalUpdate
from base_fed_learning.models.Nets import MLP, CNNMnist, CNNCifar
from base_fed_learning.models.Fed import FedAvg
from base_fed_learning.models.test import test_img, test_img_classes
from clustering import clustering_single, clustering_perfect, clustering_umap, clustering_encoder, clustering_umap_central

from manifold_approximation.models.convAE_128D import ConvAutoencoder

import os
import argparse

from utils.args import parse_args
from utils.model_utils import read_data
from torch.utils.data import Dataset
from torchvision.datasets.vision import VisionDataset
from torchvision.datasets.mnist import MNIST
import warnings
from PIL import Image

# ----------------------------------
# Reproducability
# ----------------------------------
def set_random_seed():
    torch.manual_seed(123)
    np.random.seed(321)
    umap_random_state=42

    return

def cluster_testdata_dict(dataset, dataset_type, num_users, cluster):
    """
    By: Mohammad Abdizadeh
    Sample clustered non-I.I.D client data from MNIST dataset
    Parameters:
        dataset: target dataset
        dataset_type 
        num_users
        cluster: cluster 2D array
    Returns:
        dict_users: user data sample index dictionary
    """
    cluster_size = cluster.shape[0]
    dict_users = {i: np.array([], dtype='int64') for i in range(num_users)}

    if dataset_type in ['cifar', 'CIFAR10']:
        labels = np.array(dataset.targets)
    else:
        labels = dataset.train_labels.numpy()

    nr_in_clusters = num_users // cluster_size

    for i in range(num_users):
        cluster_index = (i//nr_in_clusters)
        for k in range(len(labels)):
            if labels[k] in cluster[cluster_index]:
                dict_users[i] = np.concatenate((dict_users[i], np.array([k])), axis=0)
    
    return dict_users


from torchvision.datasets.utils import download_url, download_and_extract_archive, extract_archive, \
    verify_str_arg
from torchvision.datasets import MNIST, utils
from PIL import Image
import os.path
import torch
from torchvision.datasets.mnist import read_image_file, read_label_file
class FEMNIST(VisionDataset):
    """
    This dataset is derived from the Leaf repository
    (https://github.com/TalwalkarLab/leaf) pre-processing of the Extended MNIST
    dataset, grouping examples by writer. Details about Leaf were published in
    "LEAF: A Benchmark for Federated Settings" https://arxiv.org/abs/1812.01097.

    Args:
        root (string): Root directory of dataset where ``MNIST/processed/training.pt``
            and  ``FEMNIST/processed/test.pt`` exist.
        train (bool, optional): If True, creates dataset from ``training.pt``,
            otherwise from ``test.pt``.
        download (bool, optional): If true, downloads the dataset from the internet and
            puts it in root directory. If dataset is already downloaded, it is not
            downloaded again.
        transform (callable, optional): A function/transform that  takes in an PIL image
            and returns a transformed version. E.g, ``transforms.RandomCrop``
        target_transform (callable, optional): A function/transform that takes in the
            target and transforms it.
    """

    resources = [
        ('https://raw.githubusercontent.com/tao-shen/FEMNIST_pytorch/master/femnist.tar.gz',
         '59c65cec646fc57fe92d27d83afdf0ed')
    ]

    training_file = 'training.pt'
    test_file = 'test.pt'
    classes =  ['0',  '1',  '2',  '3',  '4',  '5',  '6',  '7',  '8',  '9',
                    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 
                    'M', 'N', 'O', 'P', 'Q','R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y',  'Z',
                    'a', 'b', 'd', 'e', 'f', 'g', 'h', 'n', 'q', 'r', 't']

    @property
    def train_labels(self):
        warnings.warn("train_labels has been renamed targets")
        return self.targets

    @property
    def test_labels(self):
        warnings.warn("test_labels has been renamed targets")
        return self.targets

    @property
    def train_data(self):
        warnings.warn("train_data has been renamed data")
        return self.data

    @property
    def test_data(self):
        warnings.warn("test_data has been renamed data")
        return self.data

    def __init__(self, root, train=True, transform=None, target_transform=None,
                 download=False):
        super(FEMNIST, self).__init__(root, transform=transform,
                                    target_transform=target_transform)
        self.train = train  # training set or test set

        if download:
            self.download()

        if not self._check_exists():
            raise RuntimeError('Dataset not found.' +
                               ' You can use download=True to download it')

        if self.train:
            data_file = self.training_file
        else:
            data_file = self.test_file
        self.data, self.targets, _ = torch.load(os.path.join(self.processed_folder, data_file))

        train_data_dir = os.path.join('..', 'data', 'femnist', 'FEMNIST', 'train')
        test_data_dir = os.path.join('..', 'data', 'femnist', 'FEMNIST', 'test')  
        self.dict_users = {}

        if self.train == True:
            self.users, groups, self.data = read_data(train_data_dir, test_data_dir, train_flag = True)
        else:
            self.users, groups, self.data = read_data(train_data_dir, test_data_dir, train_flag = False)

        counter = 0        
        for i in range(len(self.users)):
            lst = list(counter + np.arange(len(self.data[self.users[i]]['y'])))
            self.dict_users.update({i: set(lst)})
            counter = lst[-1] + 1


        self.dict_index = {}# define a dictionary to keep the location of a sample and the corresponding
        length_data = 0
        for i in range(len(self.users)):
            for j in range(len(self.data[self.users[i]]['y'])):
                self.dict_index[length_data] = [i, j]
                length_data += 1
        self.length_data = length_data
        self.num_classes = 100
        self.n_classes = 100

    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (image, target) where target is index of the target class.
        """
        [i, j] = self.dict_index[index]
        img, target = self.data[self.users[i]]['x'][j], int(self.data[self.users[i]]['y'][j])

        # doing this so that it is consistent with all other datasets
        # to return a PIL Image
        img = Image.fromarray(np.array(img).reshape(28,28), mode='L')

        if self.transform is not None:
            img = self.transform(img)

        if self.target_transform is not None:
            target = self.target_transform(target)

        return img, target

    def __len__(self):
        return self.length_data

    @property
    def raw_folder(self):
        return os.path.join(self.root, self.__class__.__name__, 'raw')

    @property
    def processed_folder(self):
        return os.path.join(self.root, self.__class__.__name__, 'processed')

    @property
    def class_to_idx(self):
        return {_class: i for i, _class in enumerate(self.classes)}

    def _check_exists(self):
        return (os.path.exists(os.path.join(self.processed_folder,
                                            self.training_file)) and
                os.path.exists(os.path.join(self.processed_folder,
                                            self.test_file)))

    def download(self):
        """Download the MNIST data if it doesn't exist in processed_folder already."""

        if self._check_exists():
            return

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.processed_folder, exist_ok=True)

        # download files
        for url, md5 in self.resources:
            filename = url.rpartition('/')[2]
            download_and_extract_archive(url, download_root=self.raw_folder, filename=filename, md5=md5)

        # process and save as torch files
        print('Processing...')
        """
        training_set = (
            read_image_file(os.path.join(self.raw_folder, 'train-images-idx3-ubyte')),
            read_label_file(os.path.join(self.raw_folder, 'train-labels-idx1-ubyte'))
        )
        test_set = (
            read_image_file(os.path.join(self.raw_folder, 't10k-images-idx3-ubyte')),
            read_label_file(os.path.join(self.raw_folder, 't10k-labels-idx1-ubyte'))
        )
        with open(os.path.join(self.processed_folder, self.training_file), 'wb') as f:
            torch.save(training_set, f)
        with open(os.path.join(self.processed_folder, self.test_file), 'wb') as f:
            torch.save(test_set, f)
        """
        os.replace(os.path.join(self.raw_folder, 'training.pt'), os.path.join(self.processed_folder, 'training.pt'))
        os.replace(os.path.join(self.raw_folder, 'test.pt'), os.path.join(self.processed_folder, 'test.pt'))

        print('Done!')

    def extra_repr(self):
        return "Split: {}".format("Train" if self.train is True else "Test")

def gen_data(iid, dataset_type, num_users, cluster):
    '''
    By: Hadi Jamali-Rad
    Data generation wrapper based on cluster structure 
    Paramters:
        iid: determines if iid sampling is employed or not
        dataset_type: target dataset  
        data_root_dir
        transforms_dict: transforms for [train, test] data 
        num_users
        cluster: cluster 2D array
        dataset_split: data split
    Returns:
        dataset_train
        dataset_test
        dict_train_users: user train data sample index dictionary 
        dict_test_users: user test data sample index dictionary
    '''
    # load dataset 
    
    if dataset_type in ['mnist', 'MNIST']:
        # trans_mnist = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
        trans_mnist = transforms.Compose([transforms.ToTensor()])
        dataset_train = MNIST('../data/mnist/', train=True, download=True, transform=trans_mnist)
        dataset_test = MNIST('../data/mnist/', train=False, download=True, transform=trans_mnist)
        # sample users
        if iid:
            dict_train_users = mnist_iid(dataset_train, num_users)
            dict_test_users = cluster_testdata_dict(dataset_test, dataset_type, num_users, cluster)
        else:
            dict_train_users = mnist_noniid_cluster(dataset_train, num_users, cluster)
            dict_test_users = cluster_testdata_dict(dataset_test, dataset_type, num_users, cluster)
    #
    elif dataset_type in ['emnist', 'EMNIST']:     
        if not iid:
            dict_train_users = emnist_noniid_cluster(dataset_train, num_users, cluster, 
                                               random_shuffle=True)
            dict_test_users = cluster_testdata_dict(dataset_test, dataset_type, num_users, cluster)
    #       
    elif dataset_type in ['cifar', 'CIFAR10']:
        if iid:
            dict_train_users = cifar_iid(dataset_train, num_users)
            dict_test_users = cluster_testdata_dict(dataset_test, dataset_type, num_users, cluster)
        else:
            dict_train_users = cifar_noniid_cluster(dataset_train, num_users, cluster)
            dict_test_users = cluster_testdata_dict(dataset_test, dataset_type, num_users, cluster)
    #
    elif dataset_type == 'femnist':
        # trans_mnist = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
        trans_mnist = transforms.Compose([transforms.ToTensor()])
        dataset_train = FEMNIST('../data/femnist/', train=True, download=True, transform=trans_mnist)
        dataset_test = FEMNIST('../data/femnist/', train=False, download=True, transform=trans_mnist)
        # sample users
        dict_train_users = dataset_train.dict_users
        dict_test_users = dataset_test.dict_users
    #
    else:
        exit('Error: unrecognized dataset')

    return dataset_train, dataset_test, dict_train_users, dict_test_users

def gen_model(dataset, dataset_train, num_users):
    img_size = dataset_train[0][0].shape

    # build model
    if args.model == 'cnn' and (dataset == 'cifar' or dataset == 'CIFAR10'):
        net_glob = CNNCifar(args=args).to(args.device)
    elif args.model == 'cnn' and (dataset == 'mnist' or dataset == 'MNIST'):
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

def FedMLAlgo(net_glob_list, w_glob_list, dataset_train, dict_users, num_users, clustering_matrix, 
                                                             cluster, cluster_length, dict_test_users, args, outputFile, outputFile_log):
    print('iteration,training_average_loss,training_accuracy,test_accuracy,training_variance,test_variance', file = outputFile)
    
    print('0, ', end = '', file = outputFile_log)
    evaluation_user_index_range = extract_evaluation_range(args)
    for idx in evaluation_user_index_range:
        print('{:.2f}, '.format(idx), end = '', file = outputFile_log)
    for idx in evaluation_user_index_range:
        print('{:.2f}, '.format(idx), end = '', file = outputFile_log)
    print('', file = outputFile_log)

    # training
    loss_train = []

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






        
        #print(clustering_matrix)
        w_glob_list = FedAvg(w_locals, clustering_matrix)

        # copy weight to net_glob
        for idx in np.arange(num_users): #TODO: fix this
            net_glob_list[idx] = copy.deepcopy(net_glob_list[0])
            net_glob_list[idx].load_state_dict(w_glob_list[idx])

        # print loss
        loss_avg = sum(loss_locals) / len(loss_locals)
        print('Round {:3d}, Average loss {:.3f}'.format(iter, loss_avg))
        loss_train.append(loss_avg)
    return loss_train, net_glob_list

def evaluate_performance(net_glob_list, dataset_train, dataset_test, cluster, cluster_length, evaluation_user_index_range, dict_users, dict_test_users, args, outputFile, outputFile_log):
    # evaluate the performance of the models on train and test datasets
    acc_train_final = np.zeros(args.num_users)
    loss_train_final = np.zeros(args.num_users)
    acc_test_final = np.zeros(args.num_users)
    loss_test_final = np.zeros(args.num_users)

    sum_weight_training = 0
    sum_weight_test = 0

    # ----------------------------------
    # testing: average over all clients
    for idx in evaluation_user_index_range:
        print("user under process: ", idx)
        acc_train_final[idx], loss_train_final[idx] = test_img_index(net_glob_list[idx], dataset_train, dict_users[idx], args)
        acc_test_final[idx], loss_test_final[idx] = test_img_index(net_glob_list[idx], dataset_test, dict_test_users[idx], args)
        
        if args.weithed_evaluation == True:
            sum_weight_training += len(dict_users[idx])
            acc_train_final[idx] = acc_train_final[idx] * len(dict_users[idx])
        
            sum_weight_test += len(dict_test_users[idx])
            acc_test_final[idx] = acc_test_final[idx] * len(dict_test_users[idx])
            
    if args.weithed_evaluation == True:
        training_accuracy = np.sum(acc_train_final[evaluation_user_index_range]) / sum_weight_training
        test_accuracy = np.sum(acc_test_final[evaluation_user_index_range]) / sum_weight_test

        training_variance = np.var(acc_train_final[evaluation_user_index_range]) / sum_weight_training
        test_variance = np.var(acc_test_final[evaluation_user_index_range]) / sum_weight_test
    else:
        training_accuracy = np.mean(acc_train_final[evaluation_user_index_range])
        test_accuracy = np.mean(acc_test_final[evaluation_user_index_range])

        training_variance = np.var(acc_train_final[evaluation_user_index_range])
        test_variance = np.var(acc_test_final[evaluation_user_index_range])

    print('Training accuracy: {:.2f}'.format(training_accuracy))
    print('Testing accuracy: {:.2f}'.format(test_accuracy))

    print('{:.2f}, '.format(training_accuracy), end = '', file = outputFile)
    print('{:.2f}, '.format(test_accuracy), end = '', file = outputFile)
    print('{:.2f}, '.format(training_variance), end = '', file = outputFile)
    print('{:.2f}'.format(test_variance), file = outputFile)

    for idx in evaluation_user_index_range:
        print('{:.2f}, '.format(acc_train_final[idx]), end = '', file = outputFile_log)
    for idx in evaluation_user_index_range:
        print('{:.2f}, '.format(acc_test_final[idx]), end = '', file = outputFile_log)
    print('', file = outputFile_log)

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

    elif args.scenario in [1, 2]:
        cluster_length = args.num_users // args.nr_of_clusters
        # generate cluster settings    
        if args.flag_with_overlap:
            cluster = np.zeros((args.nr_of_clusters, 3), dtype='int64')
            lst = np.random.choice(10, 10, replace=False) # what is this?
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

    elif args.scenario == 3:
        # scenario 3
        args.nr_of_clusters = 2
        cluster_length = args.num_users // args.nr_of_clusters
        cluster = np.zeros((args.nr_of_clusters, 5), dtype='int64')
        cluster_array = np.random.choice(10, 10, replace=False)
        if args.cluster_overlap == 0:
            cluster[0] = cluster_array[0:5]
            cluster[1] = cluster_array[5:]
        elif args.cluster_overlap == 20:
            cluster[0] = cluster_array[0:5]
            cluster[1] = cluster_array[4:9]
        elif args.cluster_overlap == 40:
            cluster[0] = cluster_array[0:5]
            cluster[1] = cluster_array[3:8]
        elif args.cluster_overlap == 60:
            cluster[0] = cluster_array[0:5]
            cluster[1] = cluster_array[2:7]
        elif args.cluster_overlap == 80:
            cluster[0] = cluster_array[0:5]
            cluster[1] = cluster_array[1:6]
        elif args.cluster_overlap == 100:
            cluster[0] = cluster_array[0:5]
            cluster[1] = cluster_array[0:5]

    elif args.target_dataset == 'EMNIST':
        nr_of_clusters = args.nr_of_clusters
        cluster_length = args.num_users // nr_of_clusters
        n_1 = 47 // (nr_of_clusters - 1)
        n_2 = 47 % n_1
        cluster = np.zeros((nr_of_clusters, n_1), dtype='int64')
        # cluster_array = np.random.choice(47, 47, replace=False)
        cluster_array = np.arange(47)
        for i in range(nr_of_clusters - 1):
            cluster[i] = cluster_array[i*n_1: i*n_1 + n_1]
        cluster[nr_of_clusters - 1][0:n_2] = cluster_array[-n_2:]

    return cluster, cluster_length

def extract_clustering(dict_users, dataset_train, cluster, args, iter):

    if args.clustering_method == 'single':
        clustering_matrix = clustering_single(args.num_users)
        
    elif args.clustering_method == 'local':
        clustering_matrix = clustering_seperate(args.num_users)

    elif args.clustering_method == 'perfect':
        clustering_matrix = clustering_perfect(args.num_users, dict_users, dataset_train, cluster, args)

        plt.figure()
        plt.imshow(clustering_matrix)
        plt.savefig(f'{args.results_root_dir}/clust_perfect_nr_users-{args.num_users}_nr_clusters_{args.nr_of_clusters}_ep_{args.epochs}_itr_{iter}.png')
        plt.close()

    elif args.clustering_method == 'umap':
        clustering_matrix, _, _ = clustering_umap(args.num_users, dict_users, dataset_train, args)

    elif args.clustering_method == 'encoder':
        args.ae_model_name = extract_model_name(args.model_root_dir, args.pre_trained_dataset)
        ae_model_dict = encoder_model_capsul(args)

        clustering_matrix, _, _, _ =\
            clustering_encoder(dict_users, dataset_train, ae_model_dict, args)

    elif args.clustering_method == 'umap_central':
        args.ae_model_name = extract_model_name(args.model_root_dir, args.pre_trained_dataset)
        ae_model_dict = encoder_model_capsul(args)

        clustering_matrix, _, _, _, _ =\
            clustering_umap_central(dict_users, cluster, dataset_train, ae_model_dict, args)
        plt.figure()
        plt.imshow(clustering_matrix)
        plt.savefig(f'{args.results_root_dir}/clust_umapcentral_nr_users-{args.num_users}_nr_clusters_{args.nr_of_clusters}_ep_{args.epochs}_itr_{iter}.png')
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

def main(args, config_file_name):
    # set the random genertors' seed
    set_random_seed()

    # ----------------------------------
    # open the output file to write the results to
    folder_name = f'{args.results_root_dir}/main_fed/scenario_{args.scenario}/{args.target_dataset}'
    
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)

    file_name = f'{folder_name}/a.csv'
    outputFile = open(file_name, 'w')

    file_name = f'{folder_name}/a_allmodels_log.csv'
    outputFile_log = open(file_name, 'w')

    print(f'Processing configuration: {config_file_name}')   

    args.iid=True
    
    # setting the clustering format
    nr_of_clusters = 1
    cluster_length = args.num_users // nr_of_clusters
    cluster = np.zeros((nr_of_clusters,10), dtype='int64')
    for i in range(nr_of_clusters):
        # TODO: should it be np.random.choice(10, 2, replace=False) for a fairer comparison?
        cluster[i] = np.random.choice(10, 10, replace=False)
    

    if args.target_dataset in ['cifar', 'CIFAR10', 'CIFAR100', 'CIFAR110']:
        transforms_dict = {    
        'train': transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))]),
        'test': transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
        }
    else:  
        transforms_dict = {
            'train': transforms.Compose([transforms.ToTensor()]),
            'test': transforms.Compose([transforms.ToTensor()])
        }

    dataset_train, dataset_test, dict_train_users, dict_test_users = gen_data(args.iid, 'femnist', args.num_users, cluster)
    args.num_users = len(dict_train_users)

    # clustering the clients
    clustering_matrix = clustering_single(args.num_users)

    net_glob, w_glob, net_glob_list, w_glob_list = gen_model(args.target_dataset, dataset_train, args.num_users)
    loss_train, net_glob_list = FedMLAlgo(net_glob_list, w_glob_list, dataset_train, dict_train_users, args.num_users, clustering_matrix, 
                                                             cluster, cluster_length, dict_test_users, args, outputFile, outputFile_log)

    # testing: average over all clients
    # testing: average over clients in a same cluster
    acc_train_final = np.zeros(args.num_users)
    loss_train_final = np.zeros(args.num_users)
    acc_test_final = np.zeros(args.num_users)
    loss_test_final = np.zeros(args.num_users)
    for idx in np.arange(0,args.num_users-1):#TODO: no need to loop over all the users!
        print("user under process: ", idx)
        #print(list(dict_users_train[idx]))
        net_glob_list[idx].eval()
        acc_train_final[idx], loss_train_final[idx] = test_img_classes(net_glob_list[idx], dataset_train, list(dict_train_users[idx]), args)
        acc_test_final[idx], loss_test_final[idx] = test_img_classes(net_glob_list[idx], dataset_test, list(dict_test_users[idx]), args)
    print('Training accuracy: {:.2f}'.format(np.average(acc_train_final[np.arange(0,args.num_users-1,cluster_length)])))
    print('Testing accuracy: {:.2f}'.format(np.average(acc_test_final[np.arange(0,args.num_users-1,cluster_length)])))

    outputFile_log.close()
    outputFile.close()

    return loss_train

if __name__ == '__main__':
    # parse args
    args = args_parser()
    args.device = torch.device('cuda:{}'.format(args.gpu) if torch.cuda.is_available() and args.gpu != -1 else 'cpu')

    # ----------------------------------
    plt.close('all')
    entries = sorted(os.listdir(f'{args.config_root_dir}/'))

    args.num_classes = 100# TODO: fix this
    config_file_name = []
    main(args, config_file_name)
