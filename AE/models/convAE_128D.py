'''
Contains the convolutional autoencode (AE) models
'''
import torch
import torch.nn as nn
import torch.nn.functional as F
  
latent_size = 128 
class ConvAutoencoder(nn.Module):
    def __init__(self):
        super(ConvAutoencoder, self).__init__()
        ## encoder layers ##
        # conv layer (depth from 1 --> 16), 3x3 kernels
        self.conv1 = nn.Conv2d(1, 16, 3, padding=1)  
        # conv layer (depth from 16 --> 4), 3x3 kernels
        self.conv2 = nn.Conv2d(16, 4, 3, padding=1)
        # pooling layer to reduce x-y dims by two; kernel and stride of 2
        self.pool = nn.MaxPool2d(2, 2)
        # dense layers
        self.fc1 = nn.Linear(7*7*4, latent_size) #flattening (input should be calculated by a forward pass - stupidity of Pytorch)
        
        ## decoder layers ##
        # decoding dense layer
        self.dec_linear_1 = nn.Linear(latent_size, 7*7*4)
        ## a kernel of 2 and a stride of 2 will increase the spatial dims by 2
        self.t_conv1 = nn.ConvTranspose2d(4, 16, 2, stride=2)
        self.t_conv2 = nn.ConvTranspose2d(16, 1, 2, stride=2)

    def forward(self, x, return_comp=True):
        ## ==== encode ==== ##
        # add hidden layers with relu activation function
        # and maxpooling after
        x = F.relu(self.conv1(x))
        x = self.pool(x)
        # add second hidden layer
        x = F.relu(self.conv2(x))
        x = self.pool(x)  
        # flatten and apply dense layer
        x = x.view(-1, 7*7*4)
        x_comp = self.fc1(x) # compressed layer
        
        ## ==== decode ==== ##
        x = self.dec_linear_1(x_comp)
        # add transpose conv layers, with relu activation function
        x = F.relu(self.t_conv1(x.view(-1, 4, 7, 7)))
        # output layer (with sigmoid for scaling from 0 to 1)
        x = torch.sigmoid(self.t_conv2(x))
                
        if return_comp:
            return x, x_comp
        else:
            return x