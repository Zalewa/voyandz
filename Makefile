init:
	pip install -r requirements.txt

install:
	python3 setup.py install

dev:
	python3 setup.py develop

rundev:
	FLASK_APP=voyandz FLASK_ENV=development flask run

clean:
	python3 setup.py clean
	rm -rf build dist voyandz.egg-info
	rm -rf voyandz/__pycache__
