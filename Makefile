.PHONY: install validate test up down status wait smoke snapshot reset
MODE ?= core
PERSISTENCE_CHECK ?= false
CONFIRM ?=

install:
	python3 -m pip install -r requirements.txt

validate:
	python3 scripts/toolkit.py validate --mode all

test:
	python3 -m unittest discover -s tests -v

up:
	python3 scripts/toolkit.py up --mode $(MODE)

down:
	python3 scripts/toolkit.py down --mode $(MODE)

status:
	python3 scripts/toolkit.py status --mode $(MODE)

wait:
	python3 scripts/toolkit.py wait --mode $(MODE)

smoke:
	python3 scripts/toolkit.py smoke --mode $(MODE) $(if $(filter true,$(PERSISTENCE_CHECK)),--persistence-check,)

snapshot:
	python3 scripts/toolkit.py snapshot --mode $(MODE)

reset:
	python3 scripts/toolkit.py reset --mode $(MODE) --confirm "$(CONFIRM)"
