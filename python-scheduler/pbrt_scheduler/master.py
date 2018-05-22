from argparse import ArgumentParser
from pbrt_scheduler.core import SchedulerMaster

def main():
    parser = ArgumentParser()
    parser.add_argument('--server-port', default=13480, type=int,
                        help='port for communication with users')
    parser.add_argument('--system-port', default=13481, type=int,
                        help='port for communication with slaves')
    parser.add_argument('--job-port-low', default=14000, type=int,
                        help='Port range for communicating with running pbrt masters')
    parser.add_argument('--job-port-high', default=14100, type=int,
                        help='Port range for communicating with running pbrt masters')
    parser.add_argument('--slots', default=None, type=str,
                        help='host:port,host:port,.. for pbrt-master processes')

    args = parser.parse_args()

    host_port_pairs = args.slots

    if host_port_pairs is None:
        host_port_pairs = []
        for port in range(args.job_port_low, args.job_port_high):
            host_port_pairs.append(('127.0.0.1', port))
    else:
        host_port_pairs = [tuple(x.split(':')) for x in host_port_pairs.split(',')]

    scheduler = SchedulerMaster(server_port=args.server_port,
                                system_port=args.system_port,
                                host_port_pairs=host_port_pairs)
    scheduler.run()


if __name__ == "__main__":
    main()