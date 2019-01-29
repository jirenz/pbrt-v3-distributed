/* -*-mode:c++; tab-width: 2; indent-tabs-mode: nil; c-basic-offset: 2 -*- */

#ifndef PBRT_STORAGE_BACKEND_LOCAL_HH
#define PBRT_STORAGE_BACKEND_LOCAL_HH

#include "backend.h"
#include "net/aws.h"
#include "net/s3.h"

class LocalStorageBackend : public StorageBackend
{
public:
  LocalStorageBackend() {}

  void put( const std::vector<storage::PutRequest> &,
            const PutCallback & = []( const storage::PutRequest & ){} ) {}

  void get( const std::vector<storage::GetRequest> &,
            const GetCallback & = []( const storage::GetRequest & ){} ) {}
};

#endif /* PBRT_STORAGE_BACKEND_LOCAL_HH */
