"""
Created on Mon Nov 23 19:44:39 2020

@author: Mohammad Abdizadeh & Hadi Jamali-Rad
@email:{moh.abdizadeh, h.jamali.rad@gmail.com}
"""
import sys
sys.path.append("./../")
sys.path.append("./../../")
sys.path.append("./")
sys.path.append("../")

import matplotlib.pyplot as plt
import copy
import numpy as np
from torchvision import datasets, transforms
import torch
import torch.optim as optim

from utils.sampling import mnist_iid, mnist_noniid, mnist_noniid_cluster, cifar_iid
from utils.options import args_parser
from models.Update import LocalUpdate
import pickle
from sklearn.cluster import KMeans
import itertools

from tqdm import tqdm

from manifold_approximation.models.convAE_128D import ConvAutoencoder
from manifold_approximation.encoder import Encoder

# ----------------------------------
# Reproducability
# ----------------------------------
torch.manual_seed(123)
np.random.seed(321)
umap_random_state=42

def gen_model(iid, dataset_type, num_users, cluster, cluster_num):
        # load dataset and split users
    if dataset_type == 'mnist':
        trans_mnist = transforms.Compose([transforms.ToTensor()])
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

def clustering_dummy(num_users, dict_users, dataset_train, args):
    clustering_matrix = np.zeros((num_users, num_users+1))
    idxs_users = np.arange(num_users)
    for idx in idxs_users:                         
        clustering_matrix[idx][0] = idx
        for idx0 in idxs_users:
            clustering_matrix[idx][idx0+1] = 1
                
    return clustering_matrix

def clustering_perfect(num_users, dict_users, dataset_train, args):
    idxs_users = np.arange(num_users)
    ar_label = np.zeros((num_users, 4))-1
    for idx in idxs_users:
        local = LocalUpdate(args=args, dataset=dataset_train, idxs=dict_users[idx])
        label_matrix = np.empty(0, dtype=int)
        for batch_idx, (images, labels) in enumerate(local.ldr_train):
            label_matrix = np.concatenate((label_matrix, labels.numpy()), axis=0)
        label_matrix = np.unique(label_matrix)
        ar_label[idx][0] = idx
        ar_label[idx][1:1+len(label_matrix)] = label_matrix
    
    clustering_matrix = np.zeros((num_users, num_users+1))
    for idx in idxs_users:                         
        clustering_matrix[idx][0] = idx
        for idx0 in idxs_users:
            if ar_label[idx][1] == ar_label[idx0][1] and ar_label[idx][2] == ar_label[idx0][2]:
                clustering_matrix[idx][idx0+1] = 1
                
    return clustering_matrix

def clustering_umap(num_users, dict_users, dataset_train, args):
    reducer_loaded = pickle.load( open( "./manifold_approximation/models/model_weights/umap_reducer_EMNIST.p", "rb" ) )
    reducer = reducer_loaded

    idxs_users = np.arange(num_users)

    centers = np.zeros((num_users, 2, 2))
    for idx in tqdm(idxs_users, desc='Clustering progress'):
        images_matrix = np.empty((0,28*28))
        local = LocalUpdate(args=args, dataset=dataset_train, idxs=dict_users[idx])
        for batch_idx, (images, labels) in enumerate(local.ldr_train):#TODO: concatenate the matrices
            # if batch_idx == 3:# TODO: abalation test
            #     break
            ne = images.numpy().flatten().T.reshape((10,28*28))
            images_matrix = np.vstack((images_matrix, ne))
        embedding1 = reducer.transform(images_matrix)
        X = list(embedding1)
        kmeans = KMeans(n_clusters=2, random_state=0).fit(np.array(X))
        centers[idx,:,:] = kmeans.cluster_centers_
    
    clustering_matrix_soft = np.zeros((num_users, num_users+1))
    clustering_matrix = np.zeros((num_users, num_users+1))

    for idx0 in idxs_users:
        clustering_matrix_soft[idx0][0] = idx0
        clustering_matrix[idx0][0] = idx0
        for idx1 in idxs_users:
            c0 = centers[idx0]
            c1 = centers[idx1]
        
            dist0 = np.linalg.norm(c0[0] - c1[0])**2 + np.linalg.norm(c0[1] - c1[1])**2
            dist1 = np.linalg.norm(c0[0] - c1[1])**2 + np.linalg.norm(c0[1] - c1[0])**2
        
            distance = min([dist0, dist1])#min (max)
            clustering_matrix_soft[idx0][idx1+1] = distance
        
            if distance < 1:
                clustering_matrix[idx0][idx1+1] = 1
            else:
                clustering_matrix[idx0][idx1+1] = 0

    return clustering_matrix, clustering_matrix_soft, centers

def clustering_encoder(num_users, dict_users, dataset_train, ae_model, ae_model_name, 
                                                        model_root_dir, manifold_dim, args):
    
    idxs_users = np.arange(num_users)

    centers = np.zeros((num_users, 2, 2))
    embedding_matrix = np.zeros((len(dict_users[0])*num_users, 2))
    for user_id in tqdm(idxs_users, desc='Custering progress'):
        local = LocalUpdate(args=args, dataset=dataset_train, idxs=dict_users[user_id])
        
        user_dataset_train = local.ldr_train.dataset
            
        # #TODO: Mo(k)h to review this! 
        encoder = Encoder(ae_model, ae_model_name, model_root_dir, 
                                    manifold_dim, user_dataset_train, user_id)
        
        encoder.autoencoder()
        encoder.manifold_approximation_umap()
        reducer = encoder.umap_reducer
        embedding1 = encoder.umap_embedding
        
        # ----------------------------------
        # use Kmeans to cluster the data into 2 clusters
        X = list(embedding1)
        embedding_matrix[user_id*len(dict_users[0]): len(dict_users[0])*(user_id + 1),:] = embedding1
        kmeans = KMeans(n_clusters=2, random_state=0).fit(np.array(X))
        centers[user_id,:,:] = kmeans.cluster_centers_
    
    clustering_matrix_soft = np.zeros((num_users, num_users+1))
    clustering_matrix = np.zeros((num_users, num_users+1))

    for idx0 in idxs_users:
        clustering_matrix_soft[idx0][0] = idx0
        clustering_matrix[idx0][0] = idx0
        for idx1 in idxs_users:
            c0 = centers[idx0]
            c1 = centers[idx1]
        
            dist0 = np.linalg.norm(c0[0] - c1[0])**2 + np.linalg.norm(c0[1] - c1[1])**2
            dist1 = np.linalg.norm(c0[0] - c1[1])**2 + np.linalg.norm(c0[1] - c1[0])**2
        
            distance = min([dist0, dist1])#min (max)
            clustering_matrix_soft[idx0][idx1+1] = distance
        
            if distance < 1:
                clustering_matrix[idx0][idx1+1] = 1
            else:
                clustering_matrix[idx0][idx1+1] = 0

    return clustering_matrix, clustering_matrix_soft, centers, embedding_matrix

if __name__ == '__main__':
    # parse args
    args = args_parser()
    args.device = torch.device('cuda:{}'.format(args.gpu) if torch.cuda.is_available() and args.gpu != -1 else 'cpu')
    args.num_users = 20
    # ----------------------------------
    plt.close('all')
    
    iid=True
    # ----------------------------------
    # generate cluster settings    
    cluster_num = 5
    cluster_length = args.num_users // cluster_num
    cluster = np.zeros((cluster_num,2), dtype='int64')
    for i in range(cluster_num):
        cluster[i] = np.random.choice(10, 2, replace=False)
     # ----------------------------------       
    manifold_dim = 2
    model_name = "model-1606927012-epoch40-latent128"
    data_root_dir = '../data'
    model_root_dir = './manifold_approximation/models/model_weights'
     # ----------------------------------       
    # model
    model = ConvAutoencoder().to(args.device)
    optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
    # ----------------------------------
    # Load the model ckpt
    checkpoint = torch.load(f'{model_root_dir}/{model_name}_best.pt')
    model.load_state_dict(checkpoint['model_state_dict'])
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    epoch = checkpoint['epoch']
    loss = checkpoint['loss']       
    # ----------------------------------
    # generate clustered data
    dataset_train, dataset_test, dict_users = gen_model(iid, args.dataset, args.num_users, cluster, cluster_num)
    # ----------------------------------    
    #average over clients in a same cluster
    clustering_matrix = clustering_perfect(args.num_users, dict_users, dataset_train, args)
    # clustering_matrix0, clustering_matrix0_soft, centers = clustering_umap(num_users, dict_users, dataset_train, args)
    clustering_matrix0, clustering_matrix0_soft, centers, embedding_matrix = clustering_encoder(args.num_users, dict_users, dataset_train, 
                                                                model, model_name, model_root_dir, manifold_dim, args)
    
    # ----------------------------------    
    # plot results
    plt.figure(1)
    plt.imshow(clustering_matrix[:,1:],cmap=plt.cm.viridis)
    plt.figure(2)
    plt.imshow(clustering_matrix0[:,1:],cmap=plt.cm.viridis)
    plt.figure(3)
    plt.imshow(-clustering_matrix0_soft[:,1:],cmap=plt.cm.viridis)

    Num_Cent = 2*cluster_length
    colors = itertools.cycle(["r"] * Num_Cent +["b"]*Num_Cent+["g"]*Num_Cent+["k"]*Num_Cent+["y"]*Num_Cent)
    plt.figure(4)
    for i in range(0,args.num_users):
        plt.scatter(centers[i][0][0],centers[i][0][1], color=next(colors))
        plt.scatter(centers[i][1][0],centers[i][1][1], color=next(colors))

    plt.figure(5)
    Num_Cent = len(dict_users[0])*cluster_length
    colors = itertools.cycle(["r"]*1 + ["b"]*1 + ["g"]*1 + ["k"]*1 + ["y"]*1)
    for i in range(cluster_num):
        plt.scatter(embedding_matrix[i*Num_Cent:(i+1)*Num_Cent, 0], embedding_matrix[i*Num_Cent:(i+1)*Num_Cent:, 1], color=next(colors))

    plt.show()
