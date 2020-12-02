# -*- coding: utf-8 -*-
"""
Created on Mon Nov 23 19:44:39 2020

@author: Mohammad
"""
import matplotlib.pyplot as plt
import copy
import numpy as np
from torchvision import datasets, transforms
import torch

from utils.sampling import mnist_iid, mnist_noniid, mnist_noniid_cluster, cifar_iid
from utils.options import args_parser
from models.Update import LocalUpdate
from models.Nets import MLP, CNNMnist, CNNCifar
from models.Fed import FedAvg
from models.test import test_img, test_img_classes
import pickle
from sklearn.cluster import KMeans
import itertools

def gen_model(iid, dataset_type, num_users, cluster, cluster_num):
        # load dataset and split users
    if dataset_type == 'mnist':
        trans_mnist = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
        dataset_train = datasets.MNIST('../data/mnist/', train=True, download=True, transform=trans_mnist)
        dataset_test = datasets.MNIST('../data/mnist/', train=False, download=True, transform=trans_mnist)
        # sample users
        if iid:
            dict_users = mnist_noniid_cluster(dataset_train, num_users, cluster, cluster_num)
        else:
            dict_users = mnist_iid(dataset_train, num_users)
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
#TODO: replace with Hadi's autoencoder
def clustering_perfect(num_users, dict_users, dataset_train, args):
        #ar_related = np.ones((args.num_users, args.num_users+1))
    idxs_users = np.arange(num_users)
    ar_label = np.zeros((num_users, 4))-1
    for idx in idxs_users:
        local = LocalUpdate(args=args, dataset=dataset_train, idxs=dict_users[idx])
        #
        #print(idx)
        ar = np.empty(0, dtype=int)
        for batch_idx, (images, labels) in enumerate(local.ldr_train):
            ar = np.concatenate((ar, labels.numpy()), axis=0)
        ar = np.unique(ar)
        ar_label[idx][0] = idx
        ar_label[idx][1:1+len(ar)] = ar
        #print(idx, ar)
    #print(ar_label)
    
    ar_related = np.zeros((num_users, num_users+1))
    for idx in idxs_users:                         
        ar_related[idx][0] = idx
        for idx0 in idxs_users:
            if ar_label[idx][1] == ar_label[idx0][1] and ar_label[idx][2] == ar_label[idx0][2]:
                ar_related[idx][idx0+1] = 1
                
    return ar_related

def clustering_umap(num_users, dict_users, dataset_train, args):
    reducer_loaded = pickle.load( open( "umap_reducer.p", "rb" ) )
    reducer = reducer_loaded

    idxs_users = np.arange(num_users)

    centers = np.zeros((num_users, 2, 2))
    for idx in idxs_users:
        if idx % (num_users//10) == 0:
            print("clustering progress", idx*100//num_users, " %")
        X = []
        aa = np.empty((0,28*28))
        local = LocalUpdate(args=args, dataset=dataset_train, idxs=dict_users[idx])
        for batch_idx, (images, labels) in enumerate(local.ldr_train):#TODO: concatenate the matrices
            # if batch_idx == 3:# TODO: abalation test
            #     break
            ne = images.numpy().flatten().T.reshape((10,28*28))
            aa = np.vstack((aa,ne))
        embedding1 = reducer.transform(aa)
        X = list(embedding1)
        kmeans = KMeans(n_clusters=2, random_state=0).fit(np.array(X))
        centers[idx,:,:] = kmeans.cluster_centers_
    
    ar_related0_soft = np.zeros((num_users, num_users+1))
    ar_related0 = np.zeros((num_users, num_users+1))

    for idx0 in idxs_users:
        ar_related0_soft[idx0][0] = idx0
        ar_related0[idx0][0] = idx0
        for idx1 in idxs_users:
            c0 = centers[idx0]
            c1 = centers[idx1]
        
            dist0 = np.linalg.norm(c0[0] - c1[0])**2 + np.linalg.norm(c0[1] - c1[1])**2
            dist1 = np.linalg.norm(c0[0] - c1[1])**2 + np.linalg.norm(c0[1] - c1[0])**2
        
            distance = min([dist0, dist1])#min (max)
            ar_related0_soft[idx0][idx1+1] = distance
        
            if distance < 1:
                ar_related0[idx0][idx1+1] = 1
            else:
                ar_related0[idx0][idx1+1] = 0

    return ar_related0, ar_related0_soft, centers

if __name__ == '__main__':
    # parse args
    args = args_parser()
    args.device = torch.device('cuda:{}'.format(args.gpu) if torch.cuda.is_available() and args.gpu != -1 else 'cpu')
    args.gpu = -1
    args.all_clients = True
    args.iid=True
    args.frac=0.1
    args.lr=0.01
    args.num_users=20#100
    args.seed=1
    args.epochs=10
    args.num_classes = 10
    
    ##########################################################################
    # case three: 100 clients with labeled from only two images for each client --> noniid --> adding clustered fed average
    iid=True
    num_users=40
    
    cluster_num = 5
    cluster_length = num_users // cluster_num
    cluster = np.zeros((cluster_num,2), dtype='int64')
    for i in range(cluster_num):
        cluster[i] = np.random.choice(10, 2, replace=False)

    dataset='mnist'
    dataset_train, dataset_test, dict_users = gen_model(iid, dataset, num_users, cluster, cluster_num)
    
    #average over clients in a same cluster
    ar_related = clustering_perfect(num_users, dict_users, dataset_train, args)
    ar_related0, ar_related0_soft, centers = clustering_umap(num_users, dict_users, dataset_train, args)
    
    plt.figure(1)
    plt.imshow(ar_related[:,1:],cmap=plt.cm.viridis)
    plt.figure(2)
    plt.imshow(ar_related0[:,1:],cmap=plt.cm.viridis)
    plt.figure(3)
    plt.imshow(-ar_related0_soft[:,1:],cmap=plt.cm.viridis)

    Num_Cent = 2*cluster_length
    colors = itertools.cycle(["r"] * Num_Cent +["b"]*Num_Cent+["g"]*Num_Cent+["k"]*Num_Cent+["y"]*Num_Cent)
    plt.figure(4)
    for i in range(0,num_users):
        plt.scatter(centers[i][0][0],centers[i][0][1], color=next(colors))
        plt.scatter(centers[i][1][0],centers[i][1][1], color=next(colors))
