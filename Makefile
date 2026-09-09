.PHONY: test deploy inventory retire

test:
	python3 -m unittest discover -s tests -v
	./tests/test_deploy.sh
	./tests/test_retire.sh

deploy:
	./scripts/deploy.sh

inventory:
	./scripts/inventory.sh

retire:
	./scripts/retire.sh
