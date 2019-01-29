from pathlib import Path
from os.path import expanduser
from symphony.commandline import SymphonyParser
from symphony.engine import SymphonyConfig, Cluster
from symphony.kube import KubeCluster
from benedict import dump_yaml_str, load_yaml_file
from pbrt_scheduler.utils import *

RESULT_FILE_PATH_FMT = "s3://cloudrt-result/results-{}x{}"
BUCKET_URL = "s3://cloudrt-jz/island_pbrt"

class Parser(SymphonyParser):
    def create_cluster(self):
        return Cluster.new('kube')

    def setup(self):
        super().setup()
        self.docker_build_settings = {}
        SymphonyConfig().set_experiment_folder('~/pbrt')
        self._setup_launch()

    def _setup_launch(self):
        parser = self.add_subparser('launch', aliases=[])
        self._add_experiment_name(parser, required=True, positional=True)
        parser.add_argument(
            'num_workers', type=int,
            help='Number of worker nodes to use'
        )
        parser.add_argument(
            '--cores-per-worker', type=int, default=48,
            help='Amount of cpu to use per worker'
        )
        # TODO
        parser.add_argument(
            '--image', type=str, default='387291866455.dkr.ecr.us-west-2.amazonaws.com/cloudrt-baseline:latest',
            help='Container image'
        )

    def action_launch(self, args):
        """
        Then create a surreal experiment
        Args:
        """
        cluster = self.cluster
        exp = cluster.new_experiment(args.experiment_name)
        RESULT_FILE_PATH = RESULT_FILE_PATH_FMT.format(args.num_workers,
                                                       args.cores_per_worker)

        master_args = ['pbrt',
                       '--dist-master',
                       '--dist-nworkers',
                       str(args.num_workers * args.cores_per_worker),
                       '--dist-port', '$SYMPH_MASTER_PORT',
                       'island.pbrt', '--minloglevel', '1',
                       '2>master-log.txt', '1>master-stdout.txt']
        #!!!
        # print(' '.join(master_args))

        master = exp.new_process('master',
                                 container_image=args.image,
                                 args=master_args)
        master.binds('master')
        master.set_env('PYTHONUNBUFFERED', '1')
        master.set_env('RESULT_FILE_PATH', RESULT_FILE_PATH)
        master.set_env('BUCKET_URL', BUCKET_URL)
        master.resource_request(cpu=0.8 * args.cores_per_worker)
        master.image_pull_policy('Always')
        master.restart_policy('Never')

        slave_args = ['pbrt', '--dist-slave',
                      '--dist-host', '$SYMPH_MASTER_HOST',
                      '--dist-port', '$SYMPH_MASTER_PORT',
                      '--nthreads', str(args.cores_per_worker),
                      'island.pbrt', '--minloglevel', '1']
        slaves = []
        for index in range(args.num_workers):
            name = 'slave-{}'.format(index)

            this_args = slave_args + ['--logtostderr',
                                      '2>slave-{}-log.txt'.format(index),
                                      '1>slave-{}-stdout.txt'.format(index)]
            #!!!
            # print(' '.join(this_args))
            slave = exp.new_process(name,
                                    container_image=args.image,
                                    args=this_args)
            slave.image_pull_policy('Always')
            slave.restart_policy('Never')
            slave.connects('master')
            slave.set_env('PYTHONUNBUFFERED', '1')
            slave.set_env('RESULT_FILE_PATH', RESULT_FILE_PATH)
            slave.set_env('BUCKET_URL', BUCKET_URL)
            slaves.append(slave)
            slave.resource_request(cpu=0.8 * args.cores_per_worker)

        for proc in exp.list_all_processes():
            # Mount nfs
            proc.mount_empty_dir(name='filesystem', use_memory=False, mount_path='/fs')

        # return
        cluster.launch(exp, force=True)


def main():
    Parser().main()

if __name__ == '__main__':
    main()
