#include "manager.h"

#include <fcntl.h>

#include "messages/utils.h"
#include "util/exception.h"

using namespace std;

namespace pbrt {

static const string TYPE_PREFIXES[] = {
    "T",   "TM",   "LIGHTS", "SAMPLER",  "CAMERA", "SCENE",
    "MAT", "FTEX", "STEX",   "MANIFEST", "TEX"};

static_assert(
    sizeof(TYPE_PREFIXES) / sizeof(string) ==
        to_underlying(SceneManager::Type::COUNT),
    "COUNT enum value for SceneManager Type must be the last entry in "
    "the enum declaration.");

string SceneManager::ObjectTypeID::to_string() const {
    return SceneManager::getFileName(type, id);
}

void SceneManager::init(const string& scenePath) {
    this->scenePath = scenePath;
    sceneFD.reset(CheckSystemCall(
        scenePath, open(scenePath.c_str(), O_DIRECTORY | O_CLOEXEC)));
}

unique_ptr<protobuf::RecordReader> SceneManager::GetReader(
    const Type type, const uint32_t id) const {
    if (!sceneFD.initialized()) {
        throw runtime_error("SceneManager is not initialized");
    }

    return make_unique<protobuf::RecordReader>(FileDescriptor(CheckSystemCall(
        "openat", openat(sceneFD->fd_num(), getFileName(type, id).c_str(),
                         O_RDONLY, 0))));
}

unique_ptr<protobuf::RecordWriter> SceneManager::GetWriter(
    const Type type, const uint32_t id) const {
    if (!sceneFD.initialized()) {
        throw runtime_error("SceneManager is not initialized");
    }

    return make_unique<protobuf::RecordWriter>(FileDescriptor(CheckSystemCall(
        "openat",
        openat(sceneFD->fd_num(), getFileName(type, id).c_str(),
               O_WRONLY | O_CREAT | O_EXCL,
               S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP | S_IROTH | S_IWOTH))));
}

string SceneManager::getFileName(const Type type, const uint32_t id) {
    switch (type) {
    case Type::Treelet:
    case Type::TriangleMesh:
    case Type::Material:
    case Type::FloatTexture:
    case Type::SpectrumTexture:
    case Type::Texture:
        return TYPE_PREFIXES[to_underlying(type)] + to_string(id);

    case Type::Sampler:
    case Type::Camera:
    case Type::Lights:
    case Type::Scene:
    case Type::Manifest:
        return TYPE_PREFIXES[to_underlying(type)];

    default:
        throw runtime_error("invalid object type");
    }
}

uint32_t SceneManager::getNextId(const Type type, const void* ptr) {
    const uint32_t id = autoIds[to_underlying(type)]++;
    if (ptr) {
        ptrIds[ptr] = id;
    }
    return id;
}

uint32_t SceneManager::getTextureId(const std::string &path) {
    if (textureNameToId.count(path)) {
        return textureNameToId[path];
    }

    return (textureNameToId[path] = autoIds[to_underlying(Type::Texture)]++);
}

void SceneManager::recordDependency(const ObjectTypeID& from,
                                    const ObjectTypeID& to) {
    dependencies[from].insert(to);
}

protobuf::Manifest SceneManager::makeManifest() const {
    protobuf::Manifest manifest;
    /* add ids for all objects */
    auto add_to_manifest = [this, &manifest](const SceneManager::Type& type) {
        size_t total_ids = autoIds[to_underlying(type)];
        for (size_t id = 0; id < total_ids; ++id) {
            ObjectTypeID type_id{type, id};
            protobuf::Manifest::Object* obj = manifest.add_objects();
            (*obj->mutable_id()) = to_protobuf(type_id);
            if (dependencies.count(type_id) > 0) {
                for (const ObjectTypeID& dep : dependencies.at(type_id)) {
                    protobuf::ObjectTypeID* dep_id = obj->add_dependencies();
                    (*dep_id) = to_protobuf(dep);
                }
            }
        }
    };

    add_to_manifest(SceneManager::Type::Treelet);
    add_to_manifest(SceneManager::Type::TriangleMesh);
    add_to_manifest(SceneManager::Type::Material);
    add_to_manifest(SceneManager::Type::FloatTexture);
    add_to_manifest(SceneManager::Type::SpectrumTexture);
    add_to_manifest(SceneManager::Type::Texture);

    return manifest;
}

map<SceneManager::Type, vector<SceneManager::Object>>
SceneManager::listObjects() {
    if (!sceneFD.initialized()) {
        throw runtime_error("SceneManager is not initialized");
    }

    if (dependencies.empty()) {
        loadManifest();
    }

    map<Type, vector<Object>> result;
    /* read the list of objects from the manifest file */
    for (auto& kv : dependencies) {
        const ObjectTypeID& id = kv.first;
        size_t size = 0;
        if (id.type != Type::TriangleMesh) {
            string filename = getFileName(id.type, id.id);
            size = roost::file_size_at(*sceneFD, filename);
        }
        result[id.type].push_back(Object(id.id, size));
    }

    return result;
}

map<SceneManager::ObjectTypeID, set<SceneManager::ObjectTypeID>>
SceneManager::listObjectDependencies() {
    if (!sceneFD.initialized()) {
        throw runtime_error("SceneManager is not initialized");
    }

    if (dependencies.empty()) {
        loadManifest();
    }

    return dependencies;
}

void SceneManager::loadManifest() {
    auto reader = GetReader(SceneManager::Type::Manifest);
    protobuf::Manifest manifest;
    reader->read(&manifest);
    for (const protobuf::Manifest::Object& obj : manifest.objects()) {
        ObjectTypeID id = from_protobuf(obj.id());
        dependencies[id] = {};
        for (const protobuf::ObjectTypeID& dep : obj.dependencies()) {
            dependencies[id].insert(from_protobuf(dep));
        }
    }
    dependencies[ObjectTypeID{Type::Scene, 0}];
    dependencies[ObjectTypeID{Type::Camera, 0}];
    dependencies[ObjectTypeID{Type::Lights, 0}];
    dependencies[ObjectTypeID{Type::Sampler, 0}];
}

namespace global {
SceneManager manager;
}

}  // namespace pbrt
