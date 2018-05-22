URL = us.gcr.io/surreal-dev-188523/jirenz-pbrt

.PHONY: build push pull publish

build:
	docker build . -f Dockerfile16 -t $(URL):latest

push:
	docker push $(URL):latest

pull:
	docker pull $(URL):latest

publish: build push