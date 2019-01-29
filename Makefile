URL = 387291866455.dkr.ecr.us-west-2.amazonaws.com/cloudrt-baseline:latest

.PHONY: build push pull publish

build:
	docker build . -f DockerfileCloudrt -t $(URL)

push:
	docker push $(URL)

pull:
	docker pull $(URL)

publish: build push