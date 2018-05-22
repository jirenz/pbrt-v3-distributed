from pathlib import Path
from os.path import expanduser
from symphony.commandline import SymphonyParser
from symphony.engine import SymphonyConfig, Cluster
from symphony.kube import KubeCluster
from symphony.addons import DockerBuilder
from benedict import dump_yaml_str, load_yaml_file

class KurrealParser(SymphonyParser):
    def create_cluster(self):
        return Cluster.new('kube')

    def setup(self):
        super().setup()
        self.docker_build_settings = {}
        SymphonyConfig().set_experiment_folder('~/pbrt')
        self._setup_deploy()
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

    def _setup_deploy(self):
        parser = self.add_subparser('deploy', aliases=[])
        self._add_experiment_name(parser, required=True, positional=True)
        parser.add_argument(
            'num_workers', type=int,
            help='Number of worker threads to use'
        )
        parser.add_argument(
            '--cores-per-worker', type=str, default='1',
            help='Amount of cpu to use per worker'
        )
        parser.add_argument(
            '--image', type=str, default='us.gcr.io/surreal-dev-188523/jirenz-pbrt:latest',
            help='Container image'
        )

    def _setup_connect(self):
        parser = self.add_subparser('connect', aliases=[])
        self._add_experiment_name(parser, required=False, positional=True)

    def action_connect(self, args):
        name = args.experiment_name
        if name is None:
            name = self.cluster.current_experiment()
        url = self.cluster.external_url(name, 'frontend')
        if url:
            host, port = url.split(':')
            print('Setting forntend url: {}'.format(url))
            self.update_config({'server_host': host, 'server_port': port})
        else:
            print('Frontend does not yet have an external IP.')

    def action_deploy(self, args):
        """
        Then create a surreal experiment
        Args:
        """
        cluster = self.cluster
        exp = cluster.new_experiment(args.experiment_name)

        n_slots = 10
        frontend_port = 13480
        host_port_map = []
        for i in range(n_slots):
            host_port_map.append('$SYMPH_SLOT_{0}_HOST:$SYMPH_SLOT_{0}_PORT'.format(i))
        host_port_map = ','.join(host_port_map)

        master_args = ['pbrt-master', '--server-port', '$SYMPH_FRONTEND_PORT',
                       '--system-port', '$SYMPH_SYSTEM_PORT',
                       '--slots', host_port_map]

        master = exp.new_process('master',
                                 container_image=args.image,
                                 command=['/bin/bash'],
                                 args=['-c', ' '.join(master_args)])
        master.binds('system')
        master.exposes({'frontend': frontend_port})
        master.set_env('PYTHONUNBUFFERED', '1')

        for i in range(10):
            master.binds('slot-{}'.format(i))

        master.image_pull_policy('Always')
        slave_args = ['--system-port', '$SYMPH_SYSTEM_PORT',
                      '--system-host', '$SYMPH_SYSTEM_HOST',
                      '--heartbeat-interval', '30']
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

        nfs_server = 'surreal-shared-fs-vm'
        nfs_server_path = '/data'
        nfs_mount_path = '/fs'
        for proc in exp.list_all_processes():
            # Mount nfs
            proc.mount_nfs(server=nfs_server, path=nfs_server_path, mount_path=nfs_mount_path)

        max_workers = args.num_workers
        fs_save_path = nfs_server_path + '/jirenz/pbrt'
        fs_read_path = nfs_mount_path + '/jirenz/pbrt'

        cluster.launch(exp, force=True)

        config_di = {
            'max_workers': max_workers,
            'fs_save_path': fs_save_path,
            'fs_read_path': fs_read_path,
            'server_port': frontend_port,
        }
        self.update_config(config_di)

def main():
    KurrealParser().main()

if __name__ == '__main__':
    main()    