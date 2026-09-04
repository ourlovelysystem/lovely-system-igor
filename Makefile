.PHONY: test deploy

test:
	python3 -m unittest discover -s tests -v

deploy:
	./scripts/deploy.sh

