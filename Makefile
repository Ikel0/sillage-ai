.PHONY: run test check

run:
	uvicorn sillage.app:app --reload --app-dir src

test:
	PYTHONPATH=src python -m unittest discover -s tests -v

check:
	python -m compileall -q src
	PYTHONPATH=src python -m unittest discover -s tests -v
