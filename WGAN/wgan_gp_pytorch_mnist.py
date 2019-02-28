# -*- coding: utf-8 -*-
"""WGAN GP Pytorch MNIST.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1_sSaLAxCAhpkinoAjAZtBGp3XgZ1BCxd
"""

from __future__ import print_function
import matplotlib.pyplot as plt
# %matplotlib inline
import torch.autograd as autograd
import argparse
import numpy as np
import os
import random
import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
import torchvision.datasets as dset
import torchvision.transforms as transforms
import torchvision.utils as vutils
import time

dataset = 'mnist'
dataroot = "data/mnist"
batchSize = 50
workers = 2
dim = 64
imageSize = 28
critic_iters = 5
lambda_gp = 10
nc = 3
nz = 100
ngf = 64
ndf = 64
num_epochs = 200000
lr = 0.0001
beta1 = 0.5
beta2 = 0.9
ngpu = 1
manualSeed = 9102
checkpoint_dir = './training_checkpoints'
outputfile = 'data/mnist/sample'
outputdim = 784

try:
    os.makedirs(outputfile)
except OSError:
    pass

cudnn.benchmark = True
random.seed(manualSeed)
torch.manual_seed(manualSeed)

cuda = torch.cuda.is_available()

dataset = dset.MNIST(root=dataroot, download=True,
                     transform=transforms.Compose([
                         transforms.Resize(imageSize),
                         transforms.ToTensor(),
                         transforms.Normalize((0.5,), (0.5,)),
                     ]))

nc = 1
assert dataset

dataloader = torch.utils.data.DataLoader(dataset, batch_size=batchSize,
                                         shuffle=True, num_workers=int(workers))

device = torch.device("cuda:0" if cuda else "cpu")
print(device)

real_batch = next(iter(dataloader))
plt.figure(figsize=(8, 8))
plt.axis("off")
plt.title("Training Images")
plt.imshow(np.transpose(vutils.make_grid(real_batch[0].to(device)[:64], padding=2, normalize=True).cpu(), (1, 2, 0)))


class Generator(nn.Module):
    def __init__(self):
        super(Generator, self).__init__()

        self.preprocess = nn.Sequential(
            nn.Linear(128, 4 * 4 * 4 * dim),
            nn.ReLU(True)
        )
        self.block1 = nn.Sequential(
            nn.ConvTranspose2d(4 * dim, 2 * dim, kernel_size=5),
            nn.ReLU(True)
        )
        self.block2 = nn.Sequential(
            nn.ConvTranspose2d(2 * dim, dim, kernel_size=5),
            nn.ReLU(True)
        )
        self.deconv_out = nn.ConvTranspose2d(dim, 1, kernel_size=8, stride=2)

        self.sigmoid = nn.Sigmoid()

    def forward(self, input):
        output = self.preprocess(input)
        output = output.view(-1, 4 * dim, 4, 4)
        # size = (b, 4d, 4, 4)
        output = self.block1(output)
        # size = (b, 2d, 8, 8)
        output = output[:, :, :7, :7]
        output = self.block2(output)
        # size = (b, d, 11,11)
        output = self.deconv_out(output)
        # size = (b, 1, 28,28)   11*s-(s-1)+(k-1)
        output = self.sigmoid(output)
        return output.view(-1, outputdim)


class Discriminator(nn.Module):
    def __init__(self):
        super(Discriminator, self).__init__()

        self.main = nn.Sequential(
            nn.Conv2d(1, dim, kernel_size=5, stride=2, padding=2),
            # size = (b, d, 14,14)
            nn.ReLU(True),

            nn.Conv2d(dim, dim * 2, kernel_size=5, stride=2, padding=2),
            # size = (b, d * 2,  7 , 7)
            nn.ReLU(True),

            nn.Conv2d(dim * 2, dim * 4, kernel_size=5, stride=2, padding=2),
            # size = (b, d * 4,  4 , 4)
            nn.ReLU(True),

        )
        self.output = nn.Linear(4 * 4 * 4 * dim, 1)

    def forward(self, input):
        input = input.view(-1, 1, 28, 28)
        out = self.main(input)
        out = out.view(-1, 4 * 4 * 4 * dim)
        out = self.output(out)
        return out.view(-1)


def sample_img(id, netG):
    noise = torch.randn(batchSize, 128, device=device)
    fake = netG(noise).view(batchSize, 1, 28, 28)
    vutils.save_image(fake,
                      '%s/fake_samples_epoch_%03d.png' % (outputfile, id),
                      nrow=10, padding=2,
                      normalize=True)


netG = Generator().to(device)
netD = Discriminator().to(device)
sample_img(0, netG)

optimizerD = optim.Adam(netD.parameters(), lr=lr, betas=(beta1, beta2))
optimizerG = optim.Adam(netG.parameters(), lr=lr, betas=(beta1, beta2))

one = torch.FloatTensor([1]).to(device)
mone = one * -1


def calc_gp(netG, real_data, fake_data):

    alpha = torch.rand(batchSize, 1)
    alpha = alpha.expand(real_data.size())
    alpha = alpha.to(device)

    print(alpha.size())
    print(real_data.size())
    print(fake_data.size())

    interpolates = alpha * real_data + (1 - alpha) * fake_data
    interpolates = interpolates.to(device)
    D_interpolates = netD(interpolates)

    interpolates = autograd.Variable(interpolates, requires_grad=True)

    grad = autograd.grad(D_interpolates, interpolates,
                         grad_outputs=torch.ones(D_interpolates.size()).cuda(0) if cuda else torch.ones(D_interpolates.size()),
                         create_graph=True, retain_graph=True, only_inputs=True)[0]



    gp = ((grad.norm(2, dim=1) - 1) ** 2).mean() * lambda_gp
    return gp


for epoch in range(num_epochs):
    start_time = time.time()
    for p in netD.parameters():
        p.requires_grad = True
    for i, data in enumerate(dataloader):
        netD.zero_grad()
        real_data = data[0].to(device)
        real_data = real_data.view(batchSize, -1)


        D_real = netD(real_data)
        D_real = D_real.mean()
        D_real.backward(mone)

        noise = torch.randn(batchSize, 128).to(device)
        fake = netG(noise).detach()
        D_fake = netD(fake)
        D_fake = D_fake.mean()
        D_fake.backward(one)

        gradient_penalty = calc_gp(netD, real_data.data, fake.data)
        gradient_penalty.backward()

        D_loss = D_fake - D_real + gradient_penalty
        Wasserstein_D = D_real - D_fake

        optimizerD.step()

        if i and i % critic_iters == 0:
            for p in netD.parameters():
                p.requires_grad = False

            netG.zero_grad()
            noise = torch.randn(batchSize, 128).to(device)
            fake = netG(noise)
            G = -netD(fake)
            G = G.mean()
            G.backward()
            optimizerG.step()

        if i % 50 == 49:
            print('[%d/%d][%d/%d] Loss_D: %.4f Loss_G: %.4f '
#                   % (epoch, num_epochs, i, len(dataloader),
                     D_loss.item(), G.item()))

        if i % 100 == 99:
            vutils.save_image(real_data,
                              '%s/real_samples.png' % outputfile,
                              normalize=True)

            sample_img(epoch, netG)

import tflib as lib