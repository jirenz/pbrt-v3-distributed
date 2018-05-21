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

    args = parser.parse_args()

    scheduler = SchedulerMaster(server_port=args.server_port,
                                system_port=args.system_port,
                                portrange=range(args.job_port_low, args.job_port_high))
    scheduler.run()


if __name__ == "__main__":
    main()