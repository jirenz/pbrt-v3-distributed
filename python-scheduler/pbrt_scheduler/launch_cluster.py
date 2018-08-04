import time
import sys
from pathlib import Path
from os.path import expanduser
from symphony.commandline import SymphonyParser
from symphony.engine import SymphonyConfig, Cluster
from symphony.kube import KubeCluster
from symphony.addons import DockerBuilder
from benedict import dump_yaml_str, load_yaml_file
from pbrt_scheduler.utils import *


class KurrealParser(SymphonyParser):
    def create_cluster(self):
        return Cluster.new('kube')

    def setup(self):
        super().setup()
        self.docker_build_settings = {}
        SymphonyConfig().set_experiment_folder('~/pbrt')
        self._setup_launch()
        self._setup_connect()

    def update_config(self, di):
        config_path = Path(expanduser('~/.pbrt-distributed.yml'))
        backup_path = Path(expanduser('~/.pbrt-distributed.yml.bak'))
        current_config = load_yaml_file(str(config_path))
        with backup_path.open('w') as f_back:
            f_back.write(dump_yaml_str(current_config))
        for key in di:
            current_config[key] = di[key]
        with config_path.open('w') as f:
            f.write(dump_yaml_str(current_config))
        print('Updated client config file')

    def _setup_launch(self):
        parser = self.add_subparser('launch', aliases=[])
        self._add_experiment_name(parser, required=True, positional=True)
        parser.add_argument(
            'num_workers', type=int,
            help='Number of worker threads to use'
        )
        parser.add_argument(
            '--cores-per-worker', type=int, default=8,
            help='Amount of cpu to use per worker'
        )
        parser.add_argument(
            '--image', type=str, default='us.gcr.io/surreal-dev-188523/jirenz-pbrt:latest',
            help='Container image'
        )
        parser.add_argument(
            '--no-wait', action='store_true',
            help='Do not wait for establishing connection'
        )
        parser.add_argument(
            '--concurrent-jobs', type=int,
            default=1, help='Number of concurrent render jobs')
        self._add_connet_args(parser)

    def _add_connet_args(self, parser):
        parser.add_argument('--no-retry')
        parser.add_argument('--retry-interval', type=int, default=10, help='Retry after <interval> seconds')


    def _setup_connect(self):
        parser = self.add_subparser('connect', aliases=[])
        self._add_connet_args(parser)
        self._add_experiment_name(parser, required=False, positional=True)

    def _connect(self, name):
        url = self.cluster.external_url(name, 'frontend')
        if url:
            host, port = url.split(':')
            print('Setting forntend url: {}'.format(url))
            self.update_config({'server_host': host, 'server_port': port})
        else:
            print('Frontend does not yet have an external IP.')

    def action_connect(self, args):
        name = args.experiment_name
        if name is None:
            name = self.cluster.current_experiment()
        if args.no_retry:
            self._connect(name)
        else:
            while True:
                try:
                    self._connect(name)
                    return
                except Exception as e:
                    print(e)
                    countdown(args.retry_interval, 'Retrying in {} s')

    def action_launch(self, args):
        """
        Then create a surreal experiment
        Args:
        """
        cluster = self.cluster
        exp = cluster.new_experiment(args.experiment_name)

        n_masters = args.concurrent_jobs
        frontend_port = 13480
        host_port_map_list = []
        for i in range(n_masters):
            # Each parallel pbrt-master requires its own host and port
            host_port_map_list.append('$SYMPH_JOBSLOT_{0}_HOST:$SYMPH_JOBSLOT_{0}_PORT'.format(i))
        host_port_map = ','.join(host_port_map_list)

        master_args = ['pbrt-master',
                       '--server-port', '$SYMPH_FRONTEND_PORT',
                       '--system-port', '$SYMPH_SYSTEM_PORT',
                       '--addresses', host_port_map,
                       '--cores-per-worker', str(args.cores_per_worker)]

        master = exp.new_process('master',
                                 container_image=args.image,
                                 command=['/bin/bash'],
                                 args=['-c', ' '.join(master_args)])
        master.binds('system')
        master.exposes({'frontend': frontend_port})
        master.set_env('PYTHONUNBUFFERED', '1')
        master.node_selector('surreal-node', 'agent')
        master.add_toleration(key='surreal', value='true', effect='NoExecute')
        master.resource_request(cpu=1.5)

        for i in range(10):
            master.binds('jobslot-{}'.format(i))

        master.image_pull_policy('Always')
        slave_args = ['--system-port', '$SYMPH_SYSTEM_PORT',
                      '--system-host', '$SYMPH_SYSTEM_HOST',
                      '--heartbeat-interval', '30',
                      '--cores-per-worker', str(args.cores_per_worker)]
        slaves = []
        for index in range(args.num_workers):
            name = 'slave-{}'.format(index)
            this_args = ['-c', ' '.join(['pbrt-slave', name] + slave_args)]
            slave = exp.new_process(name,
                                    container_image=args.image,
                                    command=['/bin/bash'],
                                    args=this_args)
            slave.image_pull_policy('Always')
            slave.connects('system')
            slave.set_env('PYTHONUNBUFFERED', '1')
            slaves.append(slave)
            slave.node_selector('surreal-node', 'nonagent-cpu')
            slave.add_toleration(key='surreal', value='true', effect='NoExecute')
            slave.resource_request(cpu=7)

        nfs_server = 'surreal-shared-fs-vm'
        nfs_server_path = '/data'
        nfs_mount_path = '/fs'
        for proc in exp.list_all_processes():
            # Mount nfs
            proc.mount_nfs(server=nfs_server, path=nfs_server_path, mount_path=nfs_mount_path)

        num_workers = args.num_workers
        fs_save_path = nfs_server_path + '/jirenz/pbrt'
        fs_read_path = nfs_mount_path + '/jirenz/pbrt'

        cluster.launch(exp, force=True)

        config_di = {
            'num_workers': num_workers,
            'fs_save_path': fs_save_path,
            'fs_read_path': fs_read_path,
            'server_port': frontend_port,
            'cores-per-worker': args.cores_per_worker,
        }
        self.update_config(config_di)

        print('Connecting...')

        self.action_connect(args)


def main():
    KurrealParser().main()

if __name__ == '__main__':
    main()