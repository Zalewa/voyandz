dist:
	python3 -m build

sdist:
	python3 setup.py sdist

init:
	pip install -r requirements.txt

install:
	python3 setup.py install

dev:
	python3 setup.py develop

rundev:
	voyandz --develop

clean:
	python3 setup.py clean
	rm -rf build dist src/voyandz.egg-info
	rm -rf src/voyandz/__pycache__

distclean: clean
	rm -rf .eggs

.PHONY: dist sdist init install dev rundev clean distclean
