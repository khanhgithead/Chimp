'''
File to initialize training.
Contains settings, network definition for Chainer.
Creates the simulator, replay memory, DQN learner, and passes these to the agent framework for training.
'''

import numpy as np

import chainer
import chainer.functions as F
import chainer.links as L
from chainer import cuda, Function, gradient_check, Variable, optimizers, serializers, utils
from chainer import Link, Chain, ChainList

from memories import ReplayMemoryHDF5

from learners import Learner
from agents import DQNAgent

from simulators.pomdp import MOMDPSimulator
from simulators.pomdp import RockSamplePOMDP

import matplotlib.pyplot as plt

print('Setting training parameters...')
# Set training settings
settings = {
    # agent settings
    'batch_size' : 32,
    'print_every' : 5000,
    'save_dir' : 'results/nets_rocksample_belief_som',
    'iterations' : 1000000,
    'eval_iterations' : 1000,
    'eval_every' : 5000,
    'save_every' : 5000,
    'initial_exploration' : 10000,
    'epsilon_decay' : 0.000001, # subtract from epsilon every step
    'eval_epsilon' : 0, # epsilon used in evaluation, 0 means no random actions
    'epsilon' : 1.0,  # Initial exploratoin rate
    'learn_freq' : 1,

    # simulator settings
    'viz' : False,

    # replay memory settings
    'memory_size' : 100000,  # size of replay memory
    'n_frames' : 1,  # number of frames

    # learner settings
    'learning_rate' : 0.00025, 
    'decay_rate' : 0.99, # decay rate for RMSprop, otherwise not used
    'discount' : 0.95, # discount rate for RL
    'clip_err' : False, # value to clip loss gradients to
    'clip_reward' : 1, # value to clip reward values to
    'target_net_update' : 1000, # update the update-generating target net every fixed number of iterations
    'double_DQN' : False, # use Double DQN (based on Deep Mind paper)
    'optim_name' : 'RMSprop', # currently supports "RMSprop", "ADADELTA" and "SGD"'
    'gpu' : True,
    'reward_rescale': False,

    # general
    'seed_general' : 1723,
    'seed_simulator' : 5632,
    'seed_agent' : 9826,
    'seed_memory' : 7563

    }

print(settings)

np.random.seed(settings["seed_general"])

print('Setting up simulator...')
pomdp = RockSamplePOMDP( seed=settings['seed_simulator'] )
simulator = MOMDPSimulator(pomdp, robs=False)

settings['model_dims'] = simulator.model_dims

print('Initializing replay memory...')
memory = ReplayMemoryHDF5(settings)

print('Setting up networks...')

class SOM(Chain):

    def __init__(self):
        super(SOM, self).__init__(
            l1=F.Linear(simulator.model_dims[0] * settings["n_frames"], 1024, wscale=np.sqrt(2)),
            l2=F.Convolution2D(1, 4, ksize=4, stride=2, nobias=False, wscale=np.sqrt(2)),
            l3=F.Convolution2D(4, 4, ksize=4, stride=2, nobias=False, wscale=np.sqrt(2)),
            l4=F.Convolution2D(4, 2, ksize=3, stride=1, nobias=False, wscale=np.sqrt(2)),
            l5=F.Linear(32, 50, wscale = np.sqrt(2)),
            l6=F.Linear(50, simulator.n_actions, wscale = np.sqrt(2))
        )

    def __call__(self, s, action_history):
        h1 = F.relu(net.l1(s/10))
        h1a = F.reshape(h1,(-1,1,32,32)) # -1 means we don't specify the number of batches
        h2 = F.relu(net.l2(h1a))
        h3 = F.relu(net.l3(h2))
        h4 = F.relu(net.l4(h3))
        h5 = F.relu(net.l5(h4))
        output = net.l6(h5)
        return output

net = SOM()

print('Initializing the learner...')
learner = Learner(net, settings)

print('Initializing the agent framework...')
agent = DQNAgent(settings)

print('Loading the net...')
learner = agent.load(settings['save_dir']+'/learner_final.p')

'''Plot training history'''

plt.plot(range(len(learner.val_rewards)), learner.val_rewards)
plt.xlabel("Evaluation episode (1000 transitions long, every 5000 training iter.)")
plt.ylabel("Accumulated reward per episode")
plt.xlim(0, 200)
plt.ylim(-2000, 2000)
plt.grid(True)
plt.savefig(settings['save_dir'] + '_' + "evaluation_reward.svg", bbox_inches='tight')
plt.close()

plt.plot(range(len(learner.val_qval_avgs)), learner.val_qval_avgs)
plt.xlabel("Evaluation episode  (1000 transitions long, every 5000 training iter.)")
plt.ylabel("Average Q-value")
plt.xlim(0, 200)
plt.ylim(0, 4)
plt.grid(True)
plt.savefig(settings['save_dir'] + '_' + "evaluation_q_value.svg", bbox_inches='tight')
plt.close()

csv_rq = np.array([range(len(learner.val_rewards)),learner.val_rewards, learner.val_qval_avgs]).T
np.savetxt('./generated_data/training_rocksample_belief_som_rmsprop.csv', csv_rq, delimiter=',')


'''Plot value surface for beliefs'''
ind_max = learner.val_rewards.index(max(learner.val_rewards))
ind_net = settings['initial_exploration'] + ind_max * settings['eval_every']
agent.load_net(learner,settings['save_dir']+'/net_%d.p' % int(ind_net))

print(ind_net)
print(ind_max)
print(learner.val_rewards[ind_max])

'''Evaluate learned policy against the optimal heuristic policy'''
np.random.seed(settings["seed_general"])

print('Evaluating DQN agent...')
print('(reward, MSE loss, mean Q-value, episodes - NA, time)')
reward, MSE_loss, mean_Q_value, episodes, time, paths, actions, rewards = agent.evaluate(learner, simulator, 50000)
print(reward, MSE_loss, mean_Q_value, episodes, time)
print(sum([sum(r) for r in rewards])/float(episodes))


for p in xrange(len(paths)):
    path = paths[p]
    rew = rewards[p]
    a = actions[p]

    l = len(path)
    x = np.zeros(l)
    y = np.zeros(l)
    for i in xrange(l):
        x[i] = path[i].squeeze()[0]
        y[i] = path[i].squeeze()[1]
        if rew[i] > 0:
            plt.plot([x[i]], [y[i]], 'o', color='lightgreen', markersize=15, alpha=0.1)

    x += np.random.normal(0.0, 0.1, x.size)
    y += np.random.normal(0.0, 0.1, y.size)
    plt.plot(x, y, color='red', alpha=0.5)

x_rocks = [2,3,5,1]
y_rocks = [4,4,5,6]

plt.plot(x_rocks, y_rocks, 'o', color='black', markersize=10, alpha=0.9)

leg, = plt.plot([],[], label="Path", color="red", alpha = 0.5)
leg_rew, = plt.plot([], marker = 'o', label="Positive reward", color="lightgreen", markersize=15, alpha=0.25, linestyle="None")
ler_rock, = plt.plot([], marker = 'o', label="Rock", color='black', markersize=10, alpha=0.9, linestyle="None")

plt.legend(handles=[leg,leg_rew,ler_rock], loc=4,numpoints=1)

plt.xlabel("X")
plt.ylabel("Y")
plt.xlim(0, 6)
plt.ylim(0, 6)
plt.grid(True)
plt.savefig(settings['save_dir'] + '_' + str(ind_net) + '_' + "paths.png", bbox_inches='tight')
plt.savefig(settings['save_dir'] + '_' + str(ind_net) + '_' + "paths.svg", bbox_inches='tight')
plt.close()


print('Evaluating optimal policy...')
print('(reward, NA, NA, episodes - NA, time)')
reward, MSE_loss, mean_Q_value, episodes, time, paths, actions, rewards = agent.evaluate(learner, simulator, 50000, custom_policy=pomdp.heuristic_policy)
print(reward, MSE_loss, mean_Q_value, episodes, time)
print(sum([sum(r) for r in rewards])/float(episodes))

