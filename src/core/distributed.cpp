#include "distributed.h"
#include "pbrt.h"
#include <iostream>
#include <iomanip>
#include <sstream>

namespace pbrt {

std::string ServerAddress() {
    std::stringstream ss;
    ss << "tcp://*:"  << PbrtOptions.port;
    return ss.str();
}

std::string ClientAddress() {
    std::stringstream ss;
    ss << "tcp://" << PbrtOptions.host << ":"  << PbrtOptions.port;
    return ss.str();
}


bool RecvNoEINTR(zmq::socket_t &socket, zmq::message_t *message_ptr, int flags) {
    while (true) {
        try {
            bool rc = socket.recv(message_ptr, flags);
            return rc;
        } catch (zmq::error_t e) {
            if (e.num() != EINTR) {
                throw e;    
            }
        }
    }
}

bool SendNoEINTR(zmq::socket_t &socket, zmq::message_t &message, int flags) {
    while (true) {
        try {
            bool rc = socket.send(message, flags);
            return rc;
        } catch (zmq::error_t e) {
            if (e.num() != EINTR) {
                throw e;    
            }
        }
    }
}

std::string s_recv (zmq::socket_t & socket) {
    zmq::message_t message;
    RecvNoEINTR(socket, &message);
    return std::string(static_cast<char*>(message.data()), message.size());
}

//  Convert string to 0MQ string and send to socket
bool s_send (zmq::socket_t & socket, const std::string & string) {
    zmq::message_t message(string.size());
    memcpy(message.data(), string.data(), string.size());
    bool rc = SendNoEINTR(socket, message);
    return rc;
}

//  Sends string as 0MQ string, as multipart non-terminal
bool s_sendmore (zmq::socket_t & socket, const std::string & string) {
    zmq::message_t message(string.size());
    memcpy(message.data(), string.data(), string.size());
    bool rc = SendNoEINTR(socket, message, ZMQ_SNDMORE);
    return rc;
}

std::string s_set_id (zmq::socket_t& socket, const int id) {
    std::stringstream ss;
    ss << std::hex << std::uppercase
        << std::setw(4) << std::setfill('0') << id;
    socket.setsockopt(ZMQ_IDENTITY, ss.str().c_str(), ss.str().length());
    return ss.str();
}

DistributedMessageType t_recv (zmq::socket_t& socket) {
    zmq::message_t message;
    RecvNoEINTR(socket, &message);
    return DistributedMessageType(* static_cast<DistributedMessageType*>(message.data()));
}

bool t_send (zmq::socket_t& socket, const DistributedMessageType type) {
    zmq::message_t message(sizeof(DistributedMessageType));
    memcpy(message.data(), &type, sizeof(DistributedMessageType));
    bool rc = SendNoEINTR(socket, message);
    return rc;
}

bool t_sendmore (zmq::socket_t& socket, const DistributedMessageType type) {
    zmq::message_t message(sizeof(DistributedMessageType));
    memcpy (message.data(), &type, sizeof(DistributedMessageType));
    bool rc = SendNoEINTR(socket, message, ZMQ_SNDMORE);
    return rc;
}

int i_recv (zmq::socket_t& socket) {
    zmq::message_t message;
    RecvNoEINTR(socket, &message);
    return int(* static_cast<int*>(message.data()));
}

bool i_send (zmq::socket_t & socket, const int number) {
    zmq::message_t message(sizeof(int));
    memcpy(message.data(), &number, sizeof(int));
    bool rc = SendNoEINTR(socket, message);
    return rc;
}

bool i_send_more (zmq::socket_t & socket, const int number) {
    zmq::message_t message(sizeof(int));
    memcpy(message.data(), &number, sizeof(int));
    bool rc = SendNoEINTR(socket, message, ZMQ_SNDMORE);
    return rc;
}

void DistributedServer::Start() {
    socket.bind(address);
}

void DistributedServer::Join() {
    StartAllWorkers();
    while ((!jobs.empty()) || (!inProgress.empty()) || (nWorkers > 0)) RecvOne();
}

/* 
 *
 *
 */
void DistributedServer::Synchronize() {
    while (workers_ready.size() < nWorkers) RecvOne();
}

/*
 * t: DistributedMessageType, s: std::string, i: int
 * Communication protocal:
 * Worker sends ((t)ready, (s)job_context)
 * Server replies by 1) ((t)terminate, (s)reason)
 *                         This can be due to:
 *                         i) job_context of worker different from server
 *                         ii) all work are finished
 *                   2) ((t)job, (i)job_id)
 * Worker sends ((t)result, (void*)data)
 * Server replies by ((t)ack)
 */
void DistributedServer::RecvOne() {
    std::string identity = s_recv(socket); //  Worker Identity
    s_recv(socket); //  Envelope delimiter
    DistributedMessageType msg_type = t_recv(socket); // Message type
    // Variables for the switch statement
    std::string worker_job_context;
    int job_id;
    zmq::message_t message;
    switch (msg_type) {
    case DistributedMessageType::ready:
        worker_job_context = s_recv(socket);
        LOG(INFO) << "Worker ready, context: " << worker_job_context;
        if (worker_job_context != jobContext) { // terminate as worker has a different pbrt file
            s_sendmore(socket, identity);
            s_sendmore(socket, "");
            t_sendmore(socket, DistributedMessageType::terminate);
            s_send(socket, "Context mismatch");
            return;
        }
        if (nReady < nWorkers) {
            // Synchronize all workers
            nReady += 1;
            workers_ready.push(identity);
        } else if (nReady == nWorkers) {
            HandleWorkerReady(identity);
        }
        break;
    case DistributedMessageType::result:
        job_id = i_recv(socket);
        LOG(INFO) << "Worker completed " << job_id;
        RecvNoEINTR(socket, &message);
        handler(job_id, message.data(), message.size());
        inProgress.erase(job_id);
        s_sendmore(socket, identity);
        s_sendmore(socket, "");
        t_send(socket, DistributedMessageType::ack);
        break;
    default:
        throw msg_type; // TODO: better error messages
    }
}

void DistributedServer::StartAllWorkers() {
    while (!workers_ready.empty()) {
        std::string identity = workers_ready.front();
        workers_ready.pop();
        HandleWorkerReady(identity);
    }
}

void DistributedServer::HandleWorkerReady(std::string identity) {
    if (jobs.size() == 0) { // terminate as there are no more jobs
        s_sendmore(socket, identity);
        s_sendmore(socket, "");
        t_sendmore(socket, DistributedMessageType::terminate);
        s_send(socket, "Completed");
        nWorkers --;
    } else {
        int job_id = jobs.front();
        inProgress.insert(job_id);
        jobs.pop();
        LOG(INFO) << "Worker starting: " << job_id;
        s_sendmore(socket, identity);
        s_sendmore(socket, "");
        t_sendmore(socket, DistributedMessageType::job);
        i_send(socket, job_id);
    }
}

// Returns whether there is a new job. 
// job_id will be populated if there is a new job
// reason will be populated if there are no jobs 
bool DistributedClient::NextJob(int & job_id) {
    if (!connected) {
        socket.connect(address);
        connected = true;
    }
    t_sendmore(socket, DistributedMessageType::ready);
    s_send(socket, jobContext);
    DistributedMessageType msg_type = t_recv(socket);
    std::string msg;
    switch (msg_type) {
    case DistributedMessageType::job:
        job_id = i_recv(socket);
        LOG(INFO) << "Worker got job: " << job_id;
        return true;
        break;
    case DistributedMessageType::terminate:
        msg = s_recv(socket);
        LOG(INFO) << "Terminated: " << msg; // TODO: use official logging
        return false;
        break;
    default:
        throw msg_type; // TODO: better error messages
    }
}

void DistributedClient::CompleteJob(const int job_id, const void * data, size_t size) {
    bool rc = t_sendmore(socket, DistributedMessageType::result);
    rc = rc && i_send_more(socket, job_id);
    
    zmq::message_t message(size);
    memcpy(message.data(), data, size);
    rc = rc && SendNoEINTR(socket, message);

    CHECK(rc);

    DistributedMessageType recv_type = t_recv(socket);
    CHECK_EQ(recv_type, DistributedMessageType::ack);
}
}  // namespace pbrt