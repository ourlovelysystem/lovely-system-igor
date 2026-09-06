.PHONY: test deploy

test:
	python3 -m unittest discover -s tests -v
	./tests/test_deploy.sh

deploy:
	./scripts/deploy.sh

