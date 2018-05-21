import time
import subprocess
import pickle
import datetime
import zmq
from threading import Thread
from collections import OrderedDict
from enum import Enum
from communication import ZmqAsyncServer, ZmqClient
import nanolog as nl


logger = nl.Logger.create_logger(
    'core',
    stream='stdout',
    time_format='MD HMS',
    show_level=True,
)


def cur_time():
    return datetime.datetime.utcnow().isoformat()

class WorkerInfo:
    def __init__(self, address):
        self.address = address
        self.current_task = None
        self.last_heartbeat = None

    def detail_dict(self):
        return {
            'name': self.address,
            'task': self.current_task,
            'last_heartbeat': self.last_heartbeat
        }

    def clear(self):
        self.current_task = None
        self.last_heartbeat = None

class MessageType(Enum):
    worker_available = 0
    worker_heartbeat = 1
    worker_complete = 2
    worker_terminate = 3 # Server side terminate

    job_complete = 4
    job_terminate = 5

    worker_newtask = 10
    heartbeat_terminate = 11

    api_assign_job = 20
    api_delete_job = 21
    api_query_jobs = 22
    api_query_job = 23
    api_query_workers = 24

    ack = 100
    error = 101
    success = 102

    def is_from_worker(self):
        return self == MessageType.worker_available \
                or self == MessageType.worker_heartbeat \
                or self == MessageType.worker_complete \
                or self == MessageType.worker_terminate


class Message:
    def __init__(self, msg_type, data):
        self.type = msg_type
        self.data = data

    def is_from_worker(self):
        return self.type.is_from_worker()

def error_message(reason):
    return Message(msg_type=MessageType.error, data={'reason':reason})

def success_message(data=None):
    if data is None:
        data = {}
    return Message(msg_type=MessageType.success, data=data)

def heartbeat_terminate_message():
    return Message(msg_type=MessageType.heartbeat_terminate, data={})

def ack_message():
    return Message(msg_type=MessageType.ack, data={})

class RenderContext:
    def __init__(self, context_name, context_folder, pbrt_file):
        self.context_name = str(context_name)
        self.context_folder = str(context_folder)
        self.pbrt_file = str(pbrt_file)

class TaskState(Enum):
    initialized = 0
    queued = 1
    running = 2
    completed = 3
    terminating = 4
    terminated = 5

class RenderTask:
    def __init__(self, name, render_context, job):
        self._render_context = render_context
        assert isinstance(job, RenderJob)
        self.job_name = job.name
        self.name = str(name)
        self._state = TaskState.initialized
        self.queued_at = None
        self.started_at = None
        self.completed_at = None
        self.terminated_at = None
        self.port = None

    def worker_dict(self):
        return {
            'name': self.name,
            'context_folder': self._render_context.context_folder,
            'pbrt_file': self._render_context.pbrt_file,
            'port': self.port
        }

    def detail_dict(self):
        return {
            'name': self.name,
            'state': self.state,
            'started_at': self.started_at,
            'queued_at': self.queued_at,
            'completed_at': self.completed_at,
            'terminated_at': self.terminated_at,
        }

    @property
    def state(self):
        return self._state

    def state_queued(self):
        assert self.state == TaskState.initialized
        self._state = TaskState.queued
        self.queued_at = cur_time()

    def state_running(self):
        assert self.state == TaskState.queued
        self._state = TaskState.running
        self.started_at = cur_time()

    def state_completed(self):
        assert self.state == TaskState.completed
        self._state = TaskState.completed
        self.completed_at = cur_time()

    def state_terminating(self):
        if self.state != TaskState.terminating and self.state != TaskState.terminated:
            self._state = TaskState.terminating
            self.terminated_at = cur_time()

    def state_terminated(self):
        if self.state != TaskState.terminated:
            self._state = TaskState.terminated
            self.terminated_at = cur_time()

class JobState(Enum):
    initialized = 0
    queued = 1
    running = 2
    # completed = 3
    terminating = 4

class RenderJob:
    def __init__(self, context_name, context_folder, pbrt_file, max_workers):
        self._render_context = RenderContext(context_name, context_folder, pbrt_file)
        self.tasks = []
        self._state = JobState.initialized
        self.queued_at = None
        self.started_at = None
        self.terminated_at = None
        self.info = ''
        self.port = None
        for i in range(max_workers):
            task = RenderTask(self._task_name(i), self._render_context, self)
            self.tasks.append(task)

    def args(self):
        return ['pbrt', self._render_context.pbrt_file, '--dist-master',
                '--dist-nworkers', str(len(self.tasks)), '--dist-port', str(self.port)]

    @property
    def context_folder(self):
        return self._render_context.context_folder

    def _task_name(self, index):
        return '-'.join([self.name, str(index)])

    @property
    def name(self):
        return self._render_context.context_name

    @property
    def terminated_count(self):
        count = 0
        for task in self.tasks:
            if task.state == TaskState.terminated:
                count += 1
        return count

    @property
    def terminating_count(self):
        count = 0
        for task in self.tasks:
            if task.state == TaskState.terminating:
                count += 1
        return count

    @property
    def completed_count(self):
        count = 0
        for task in self.tasks:
            if task.state == TaskState.completed:
                count += 1
        return count

    @property
    def running_count(self):
        count = 0
        for task in self.tasks:
            if task.state == TaskState.running:
                count += 1
        return count

    @property
    def queued_count(self):
        count = 0
        for task in self.tasks:
            if task.state == TaskState.queued:
                count += 1
        return count

    @property
    def state(self):
        return self._state

    def state_queued(self):
        assert self.state == JobState.initialized
        self._state = JobState.queued
        self.queued_at = cur_time()

    def state_running(self):
        assert self.state == JobState.queued
        self._state = JobState.running
        self.started_at = cur_time()

    def state_terminating(self):
        if self.state != JobState.terminating:
            self._state = JobState.terminating
            self.terminated_at = cur_time()

    def summary_dict(self):
        return {
            'name': self.name,
            'state': self.state.name,
            'terminating_tasks': self.terminating_count,
            'terminated_tasks': self.terminated_count,
            'completed_tasks': self.completed_count,
            'running_tasks': self.running_count,
            'queued_tasks': self.queued_count,
            'total_tasks': len(self.tasks),
            'info': self.info,
            # TODO: give a duration of current state
        }

    def detail_dict(self):
        summary = self.summary_dict()
        di = {
            'name': self.name,
            'context_folder': self._render_context.context_folder,
            'pbrt_file': self._render_context.pbrt_file,
            'state': self.state.name,
            'tasks': [task.detail_dict() for task in self.tasks],
            'queued_at': self.queued_at,
            'started_at': self.started_at,
            'terminated_at': self.terminated_at,
        }
        for k, v in summary.items():
            di[k] = v
        return di


class JobRunner(Thread):
    def __init__(self, job, port):
        super().__init__()
        self.job = job
        self.port = port
        self.terminated = False
        self.proc = None

    def terminate_job(self):
        while self.proc is None: 
        # Very rare, in case there is a race condition in delete
            time.sleep(1)
        if not self.terminated:
            self.terminated = True
            self.proc.terminate()

    def run(self):
        # TODO: !!IMPORTANT io redirect
        self.proc = subprocess.Popen(self.job.args(),
                                     stdin=None,
                                     stdout=None,
                                     stderr=None,
                                     shell=False,
                                     cwd=self.job.context_folder)
        self.proc.wait()
        returncode = self.proc.returncode
        logger.info('proc exits return code {}'.format(returncode))
        client = ZmqClient(host='127.0.0.1',
                           port=self.port,
                           serializer=pickle.dumps,
                           deserializer=pickle.loads)
        if returncode == 0:
            msg = client.request(Message(MessageType.job_complete, {'job_name': self.job.name}))
        else:
            msg = client.request(Message(MessageType.job_terminate,
                                {'returncode': returncode, 
                                 'job_name': self.job.name}))
        assert msg.type == MessageType.ack


class SchedulerMaster:
    def __init__(self, server_port, system_port, portrange):
        self.server_port = int(server_port)
        self.system_port = int(system_port)
        self.workers = {}
        self.jobs = {}
        self.running_tasks = {}
        self.available_ports = list(portrange)
        self.port_runner_map = {}
        self.queued_jobs = OrderedDict()
        self.queued_tasks = OrderedDict()
        self.queued_workers = OrderedDict()

        self.zmq_context = None
        self.system_server = None
        self.api_server = None

    def run(self):
        self.setup()
        self.main_loop()

    def setup(self):
        self.zmq_context = zmq.Context()
        self.poller = zmq.Poller()
        
        self.system_server = ZmqAsyncServer(host='*',
                                            port=self.system_port,
                                            serializer=pickle.dumps,
                                            deserializer=pickle.loads,
                                            load_balanced=False)
        self.api_server = ZmqAsyncServer(host='*',
                                         port=self.server_port,
                                         serializer=pickle.dumps,
                                         deserializer=pickle.loads,
                                         load_balanced=False)
        self.poller.register(self.system_server.socket.unwrap(), zmq.POLLIN)
        self.poller.register(self.api_server.socket.unwrap(), zmq.POLLIN)

    def main_loop(self):
        while True: # TODO: can add draining and shut down
            self._handle_api_msgs()
            self._handle_system_msgs()
            self._start_jobs()
            self._start_tasks()
            self.poller.poll()

    def _handle_api_msgs(self):
        while True:
            address, message = self.api_server.recv()
            if address:
                logger.debug('API message: {} - {}'.format(message.type.name, message.data))
                self._handle_api_msg(address, message)
            else:
                break

    def _handle_api_msg(self, address, message):
        if not isinstance(message, Message):
            raise ValueError('APIServer received incorrect type: {}' \
                             .format(type(message)))
        if message.type == MessageType.api_assign_job:
            self._handle_assign_job(address, message)
        elif message.type == MessageType.api_delete_job:
            self._handle_delete_job(address, message)
        elif message.type == MessageType.api_query_jobs:
            self._handle_query_jobs(address, message)
        elif message.type == MessageType.api_query_job:
            self._handle_query_job(address, message)
        elif message.type == MessageType.api_query_workers:
            self._handle_query_workers(address, message)
        else:
            raise ValueError('APIServer received {} unexpectedly'.format(message.type))

    def _api_data_valid(self, address, di, expected_keys, endpoint_name):
        """
        Returns True if data provided is valid, else send error response to address
        Args:
        """
        for expected_key in expected_keys:
            if expected_key not in di:
                error_reason = 'Missing field {} for "{}", needed: {}' \
                               .format(expected_key, endpoint_name, ', '.join(expected_keys))
                self.api_server.send(address, error_message(error_reason))
                return False
        return True

    def _handle_assign_job(self, address, message):
        di = message.data
        expected_keys = ['context_name', 'context_folder', 'pbrt_file', 'max_workers']
        if not self._api_data_valid(address, di, expected_keys, 'Assign Job'):
            return
        job = RenderJob(context_name=str(di['context_name']),
                        context_folder=str(di['context_folder']),
                        pbrt_file=str(di['pbrt_file']),
                        max_workers=int(di['max_workers']))
        if job.name in self.jobs:
            error_reason = 'Duplicate job {}'.format(job.name)
            self.api_server.send(address, error_message(error_reason))
        else:
            self.jobs[job.name] = job
            self.queued_jobs[job.name] = job
            job.state_queued()
            self.api_server.send(address, success_message({}))

    def _handle_delete_job(self, address, message):
        di = message.data
        expected_keys = ['job_name']
        if not self._api_data_valid(address, di, expected_keys, 'Delete Job'):
            return
        job_name = str(di['job_name'])
        if job_name not in self.jobs:
            error_reason = 'Job {} not found'.format(job_name)
            self.api_server.send(address, error_message(error_reason))
        else:
            job = self.jobs[job_name]
            job.info = 'Terminated by User'
            self._terminate_job(job)
            self.api_server.send(address, success_message)

    def _terminate_job(self, job):
        """
        Assumes that self.jobs[job.name] is job
        """
        job_name = job.name
        if job.state == JobState.queued:
            del self.queued_jobs[job_name]
        if job.state == JobState.running:
            runner = self.port_runner_map[job.port]
            runner.terminate_job()
        job.state_terminating()
        for task in job.tasks:
            if task.state == TaskState.queued:
                del self.queued_tasks[task.name]
                task.state_terminated()
            elif task.state == TaskState.running:
                task.state_terminating()
            else:
                task.state_terminated()
        self._check_complete(job)

    def _check_complete(self, job):
        if job.terminated_count + job.completed_count == len(job.tasks):
            if job.port is not None:
                self._release_port(job.port)
                job.port = None
            del self.jobs[job.name]

    def _release_port(self, port):
        del self.port_runner_map[port]
        self.available_ports.append(port)

    def _claim_port(self):
        return self.available_ports.pop()

    def _handle_query_jobs(self, address, message):
        resp = []
        for name, job in self.jobs.items():
            resp.append(job.summary_dict())
        self.api_server.send(address, success_message({'jobs': resp}))

    def _handle_query_job(self, address, message):
        di = message.data
        expected_keys = ['job_name']
        if not self._api_data_valid(address, di, expected_keys, 'Query Job'):
            return
        job_name = str(di['job_name'])
        if job_name not in self.jobs:
            error_reason = 'Job {} not found'.format(job_name)
            self.api_server.send(address, error_message(error_reason))
        else:
            job = self.jobs[job_name]
            self.api_server.send(address, success_message(job.detail_dict()))

    def _handle_query_workers(self, address, message):
        resp = []
        for _, worker_info in self.workers.items():
            resp.append(worker_info.detail_dict())
        self.api_server.send(address, success_message({'workers': resp}))

    def _handle_system_msgs(self):
        while True:
            address, message = self.system_server.recv()
            if address:
                logger.debug('System message: {} - {}'.format(message.type.name, message.data))
                self._handle_system_msg(address, message)
            else:
                break

    def _handle_system_msg(self, address, message):
        if not isinstance(message, Message):
            raise ValueError('SystemServer received incorrect type: {}' \
                             .format(type(message)))
        if message.is_from_worker():
            if address not in self.workers:
                self.workers[address] = WorkerInfo(address)

        if message.type == MessageType.worker_available:
            self._handle_worker_available(address, message)
        elif message.type == MessageType.worker_heartbeat:
            self._handle_worker_heartbeat(address, message)
        elif message.type == MessageType.worker_complete:
            self._handle_worker_complete(address, message)
        elif message.type == MessageType.worker_terminate:
            self._handle_worker_terminate(address, message)
        elif message.type == MessageType.job_complete:
            self._handle_job_complete(address, message)
        elif message.type == MessageType.job_terminate:
            self._handle_job_terminate(address, message)
        else:
            raise ValueError('WorkerServer received {} unexpectedly from worker: {}' \
                             .format(message.type, address))

    def _handle_worker_available(self, address, message):
        """
        This method does not respond anything
        This keeps the worker waiting for response
        """
        worker = self.workers[address]
        worker.current_job = None
        self.queued_workers[address] = worker

    def _verify_worker_report(self, worker, task_name):
        if task_name != worker.current_task:
            raise ValueError('Worker has task {} but server expected {}' \
                             .format(task_name, worker.current_task))
        if task_name not in self.running_tasks:
            raise ValueError('Worker has task {} but server does not expect that' \
                             .format(task_name))

    def _handle_worker_heartbeat(self, address, message):
        worker = self.workers[address]
        task_name = message.data['task_name']
        self._verify_worker_report(worker, task_name)
        worker.last_heartbeat = cur_time()
        task = self.running_tasks[task_name]
        if task.state == TaskState.running:
            self.system_server.send(address, ack_message())
        if task.state == TaskState.terminating:
            self.system_server.send(address, heartbeat_terminate_message())

    def _handle_worker_complete(self, address, message):
        worker = self.workers[address]
        task_name = message.data['task_name']
        self._verify_worker_report(worker, task_name)
        worker.clear()

        task = self.running_tasks[task_name]
        task.state_completed()
        del self.running_tasks[task_name]

        job = self.jobs[task.job_name]
        self._check_complete(job)

        self.system_server.send(address, ack_message())

    def _handle_worker_terminate(self, address, message):
        worker = self.workers[address]
        task_name = message.data['task_name']
        returncode = message.data['returncode']
        self._verify_worker_report(worker, task_name)
        worker.clear()

        task = self.running_tasks[task_name]
        task.state_terminated()
        del self.running_tasks[task_name]

        job = self.jobs[task.job_name]
        if job.state != JobState.terminating:
            job.info = 'Worker side error ({})'.format(returncode)
            self._terminate_job(job)
        self._check_complete(job)

        self.system_server.send(address, ack_message())

    def _handle_job_complete(self, address, message):
        di = message.data
        job_name = di['job_name']
        job = self.jobs[job_name]
        job.info = 'Completed (0)'
        self.system_server.send(address, ack_message())

    def _handle_job_terminate(self, address, message):
        di = message.data
        job_name = di['job_name']
        job = self.jobs[job_name]
        job.info = 'Terminated ({})'.format(di['returncode'])
        self._terminate_job(job)
        self.system_server.send(address, ack_message())

    def _start_jobs(self):
        while len(self.available_ports) > 0 and len(self.queued_jobs) > 0:
            port = self._claim_port()
            job_name, job = self.queued_jobs.popitem(last=False)
            job.state_running()
            self._start_job(job, port)
            print('job started on port {}'.format(port))

    def _start_job(self, job, port):
        job.port = port
        runner = JobRunner(job, self.system_port)
        self.port_runner_map[port] = runner
        runner.start()
        for task in job.tasks:
            task.port = port
            task.state_queued()
            self.queued_tasks[task.name] = task

    def _start_tasks(self):
        while len(self.queued_workers) > 0 and len(self.queued_tasks) > 0:
            _, worker = self.queued_workers.popitem()
            _, task = self.queued_tasks.popitem()
            self._start_task(worker, task)

    def _start_task(self, worker, task):
        if task.state != TaskState.queued:
            raise ValueError('Attempting to starting a task in state {}' \
                             .format(task.state.name))
        task.state_running()
        self.running_tasks[task.name] = task
        message = Message(MessageType.worker_newtask, data=task.worker_dict())
        worker.current_task = task.name
        self.system_server.send(worker.address, message)


class SchedulerSlave:
    def __init__(self, *, name, master_host, master_port, heartbeat_interval=5):
        self.name = name
        self.host = master_host
        self.port = master_port
        self.client = ZmqClient(host=master_host,
                                port=master_port,
                                serializer=pickle.dumps,
                                deserializer=pickle.loads,
                                name=name)
        self.current_task = None
        self.proc = None
        self.heartbeat_interval = heartbeat_interval

    def run(self):
        while True:
            if self.current_task is None:
                resp = self.client.request(Message(MessageType.worker_available, {}))
                assert resp.type == MessageType.worker_newtask
                self.start_task(resp.data)
            else:
                if self.proc.poll() is not None:
                    returncode = self.proc.returncode
                    self.proc = None
                    task = self.current_task
                    self.current_task = None
                    if returncode == 0:
                        resp = self.client.request(Message(MessageType.worker_complete,
                                                   {'task_name': task}))
                    else:
                        resp = self.client.request(Message(MessageType.worker_terminate,
                                                  {'task_name': task,
                                                  'returncode': returncode}))
                    assert resp.type == MessageType.ack
                else:
                    resp = self.client.request(Message(MessageType.worker_heartbeat,
                                             {'task_name': self.current_task}))
                    if resp.type == MessageType.heartbeat_terminate:
                        self.proc.terminate()
                    else:
                        assert resp.type == MessageType.ack
                    time.sleep(self.heartbeat_interval)

    def start_task(self, di):
        self.current_task = di['name']
        # TODO: io redirecting
        self.proc = subprocess.Popen(self.task_args(di['pbrt_file'], di['port']),
                                     stdout=None,
                                     stderr=None,
                                     cwd=di['context_folder'])

    def task_args(self, pbrt_file, port):
        return ['pbrt', pbrt_file, '--dist-slave', '--dist-host', self.host,
                '--dist-port', str(port)]

