#!/usr/bin/env python
import sys
import os
import time
import traceback
import wandb
import socket
import torch
import random
import logging
import numpy as np
from pathlib import Path
import setproctitle


sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
from config import get_config
from runner.share_jsbsim_runner import ShareJSBSimRunner
from envs.JSBSim.envs import SingleCombatEnv, SingleControlEnv, MultipleCombatEnv
from envs.env_wrappers import SubprocVecEnv, DummyVecEnv, ShareSubprocVecEnv, ShareDummyVecEnv

from envs.JSBSim.human_agent.HumanAgent import HumanAgent
from envs.JSBSim.envs.singlecontrol_env import SingleControlEnv
from envs.JSBSim.tasks.heading_task import HeadingTask  

from scripts.train.train_jsbsim import parse_args, make_train_env,make_eval_env
from runner.tacview import Tacview
def main(args):
    parser = get_config()
    all_args = parse_args(args, parser)
    
    # seed
    np.random.seed(all_args.seed)
    random.seed(all_args.seed)
    torch.manual_seed(all_args.seed)
    torch.cuda.manual_seed_all(all_args.seed)

    # cuda
    if all_args.cuda and torch.cuda.is_available():
        logging.info("choose to use gpu...")
        device = torch.device("cuda:0")  # use cude mask to control using which GPU
        torch.set_num_threads(all_args.n_training_threads)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = True
    else:
        logging.info("choose to use cpu...")
        device = torch.device("cpu")
        torch.set_num_threads(all_args.n_training_threads)

    # run dir
    run_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/results") \
        / all_args.env_name / all_args.scenario_name / all_args.algorithm_name / all_args.experiment_name
    if not run_dir.exists():
        os.makedirs(str(run_dir))

    # wandb
    if all_args.use_wandb:
        run = wandb.init(config=all_args,
                         project=all_args.env_name,
                         notes=socket.gethostname(),
                         name=f"{all_args.experiment_name}_seed{all_args.seed}",
                         group=all_args.scenario_name,
                         dir=str(run_dir),
                         job_type="training",
                         reinit=True)
    else:
        if not run_dir.exists():
            curr_run = 'run1'
        else:
            exst_run_nums = [int(str(folder.name).split('run')[1]) for folder in run_dir.iterdir() if str(folder.name).startswith('run')]
            if len(exst_run_nums) == 0:
                curr_run = 'run1'
            else:
                curr_run = 'run%i' % (max(exst_run_nums) + 1)
        run_dir = run_dir / curr_run
        if not run_dir.exists():
            os.makedirs(str(run_dir))

    setproctitle.setproctitle(str(all_args.algorithm_name) + "-" + str(all_args.env_name)
                              + "-" + str(all_args.experiment_name) + "@" + str(all_args.user_name))

    # env init
    envs = make_train_env(all_args)
    eval_envs = make_eval_env(all_args) if all_args.use_eval else None

    config = {
        "all_args": all_args,
        "envs": envs,
        "eval_envs": eval_envs,
        "device": device,
        "run_dir": run_dir
    }

    # You can pass your configuration or initialize environment here
    
    tacview = Tacview()
    
    env = SingleControlEnv(all_args.scenario_name)  # Initialize environment
    
    # Initialize HumanAgent, directly pass env
    agent = HumanAgent(env)  # No need to explicitly pass task, env already contains it

   # Reset environment and get initial observation state
    observation = agent.reset()

    
    done = False  # Initialize done as False, indicating not finished yet
    timestamp = 0 # use for tacview real time render 
    while not done:
        try:
            # Execute one step
            observation, reward, done, info = agent.step()  # Ensure calling step method
            
            # real render with tacview
            render_data = [f"#{timestamp:.2f}\n"]
            for sim in env._jsbsims.values():
                log_msg = sim.log()
                if log_msg is not None:
                    render_data.append(log_msg + "\n")

            render_data_str = "".join(render_data)
            try:
                tacview.send_data_to_client(render_data_str)
            except Exception as e:
                logging.error(f"Tacview rendering error: {e}")
                # Print call stack information
                logging.error("".join(traceback.format_exc()))

            timestamp += 0.2  # step 0.2s
            # print(timestamp)

            # You can add appropriate delay control to avoid too fast execution
            time.sleep(0.1)  # Set interval time between each step (in seconds), adjust as needed

        except Exception as e:
            logging.error(f"An error occurred: {e}")
            # Print complete call stack information
            logging.error("".join(traceback.format_exc()))
            break  # Optionally exit loop

if __name__ == "__main__":
    #logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    
    logging.basicConfig(
        level=logging.DEBUG,               # Set log level to DEBUG, meaning record all levels of logs
        format='%(asctime)s - %(levelname)s - %(message)s',  # Set log format
        filename='debug.log',              # Specify log file name
        filemode='w'                        # 'w' means write mode, 'a' means append mode
    )
    
    main(sys.argv[1:])