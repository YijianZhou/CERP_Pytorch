""" Training PpkNet (RNN)
"""
import os, time
import argparse
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, RandomSampler, BatchSampler
import torch.multiprocessing as mp
from dataset import Sequences
from models import PpkNet
import config
from tensorboardX import SummaryWriter
import warnings
warnings.filterwarnings("ignore")

def main():
  # set defaults
  torch.backends.cudnn.benchmark = True
  # i/o paths
  ckpt_dir = args.ckpt_dir
  if not os.path.exists(ckpt_dir): os.makedirs(ckpt_dir)
  # training params
  cfg = config.Config()
  lr = cfg.rnn_lr
  num_epochs = cfg.rnn_num_epochs
  summary_step = cfg.rnn_summary_step
  ckpt_step = cfg.rnn_ckpt_step
  to_init = cfg.to_init_rnn
  # seq config
  num_steps = cfg.num_steps
  step_stride = cfg.step_stride
  # set data loader
  batch_size = cfg.rnn_batch_size
  num_workers = cfg.rnn_num_workers
  train_set = Sequences(args.zarr_path, 'train')
  valid_set = Sequences(args.zarr_path, 'valid')
  train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=num_workers, pin_memory=True)
  valid_sampler = BatchSampler(RandomSampler(valid_set, replacement=True), batch_size=batch_size, drop_last=False)
  valid_loader = DataLoader(valid_set, batch_sampler=valid_sampler, pin_memory=True)
  num_batch = len(train_loader)

  # import model
  model = PpkNet()
  if to_init: model.apply(init_weights)
  device = torch.device("cuda")
  model.to(device)
#  model = nn.DataParallel(model.cuda(), device_ids=gpus, output_device=gpus[0])
  # loss & optim
  criterion = nn.CrossEntropyLoss()
  optimizer = optim.Adam(model.parameters(), lr=lr)

  # train loop
  t = time.time()
  for epoch_idx in range(num_epochs):
    for iter_idx, (data, target) in enumerate(train_loader):
        global_step = num_batch * epoch_idx + iter_idx
        # to cuda & reshape data
        data, target = data.cuda(non_blocking=True), target.cuda(non_blocking=True)
        train_acc, train_loss = train_step(model, data, target, criterion, optimizer)
        train_dt = num_steps * (1-train_acc) * step_stride / 2
        # save model
        if global_step % ckpt_step == 0: 
            torch.save(model.state_dict(), os.path.join(ckpt_dir,'%s_%s-%s.ckpt'%(global_step, epoch_idx, iter_idx)))
        # valid & print summary
        if global_step % summary_step != 0: continue
        for (data, target) in valid_loader:
            # to cuda & reshape data
            data, target = data.cuda(non_blocking=True), target.cuda(non_blocking=True)
            valid_acc, valid_loss = valid_step(model, data, target, criterion)
            valid_dt = num_steps * (1-valid_acc) * step_stride / 2
            break
        # visualization
        print('step {} ({}/{}) | train loss {:.2f} | valid loss {:.2f} | {:.2f}s'\
            .format(global_step, iter_idx, epoch_idx, train_loss, valid_loss, time.time()-t))
        print('    sequence label acc. train {:.2f}% ({:.2f}s) | valid {:.2f}% ({:.2f}s)'\
            .format(100*train_acc, train_dt, 100*valid_acc, valid_dt))
        sum_loss = {'train_loss':train_loss, 'valid_loss':valid_loss}
        sum_acc = {'train_acc':train_acc*100, 'valid_acc':valid_acc*100}
        sum_dt = {'train_dt':train_dt, 'valid_dt':valid_dt}
        with SummaryWriter(log_dir=ckpt_dir) as writer:
            writer.add_scalars('loss', sum_loss, global_step)
            writer.add_scalars('seq_acc', sum_acc, global_step)
            writer.add_scalars('dt_sec', sum_dt, global_step)


# train one batch
def train_step(model, data, target, criterion, optimizer):
    model.train()
    # prediction
    pred_logits = model(data)
    pred_logits = pred_logits.view(-1,3)
    pred_class = torch.argmax(pred_logits,1)
    target = target.view(-1)
    loss = criterion(pred_logits, target)
    acc_seq = pred_class.eq(target).sum() / float(target.size(0))
    # update weights
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return acc_seq.item(), loss.item()


# valid one batch
def valid_step(model, data, target, criterion):
    model.eval()
    # prediction
    pred_logits = model(data)
    pred_logits = pred_logits.view(-1,3)
    pred_class = torch.argmax(pred_logits,1)
    target = target.view(-1)
    loss = criterion(pred_logits, target)
    acc_seq = pred_class.eq(target).sum() / float(target.size(0))
    return acc_seq.item(), loss.item()


# initialize weights of model
def init_weights(m):
    if isinstance(m, nn.Linear):
        nn.init.kaiming_uniform_(m.weight)
        nn.init.constant_(m.bias, 0)
    elif isinstance(m, nn.GRU):
        for name, param in m.named_parameters():
            if 'weight_ih' in name: nn.init.xavier_uniform_(param.data)
            elif 'weight_hh' in name: nn.init.orthogonal_(param.data)
            elif 'bias' in name: param.data.fill_(0)

 
if __name__ == '__main__':
  mp.set_start_method('spawn', force=True) # 'spawn' or 'forkserver'
  parser = argparse.ArgumentParser()
  parser.add_argument('--gpu_idx', type=str, default="0")
  parser.add_argument('--zarr_path', type=str)
  parser.add_argument('--ckpt_dir', type=str,
    default='output/example_ckpt/PpkNet')
  parser.add_argument('--resume', default=False)
  args = parser.parse_args()
  os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_idx
  main()
