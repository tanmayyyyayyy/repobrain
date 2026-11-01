"""Dependency Guard: typosquat and supply-chain checks on dependencies an AI (or human) just added."""
import json, re

PY_POPULAR = set("""requests numpy pandas scipy matplotlib flask django fastapi pytest pyyaml boto3 botocore urllib3 setuptools pip
wheel six certifi idna charset-normalizer cryptography pydantic sqlalchemy jinja2 click werkzeug markupsafe pillow scikit-learn
tensorflow torch transformers openai anthropic httpx aiohttp beautifulsoup4 lxml selenium redis celery psycopg2 psycopg2-binary pymongo
uvicorn gunicorn typing-extensions python-dateutil pytz attrs packaging protobuf grpcio tqdm rich black flake8 mypy pylint isort
coverage tox poetry pipenv virtualenv docutils sphinx joblib networkx seaborn plotly streamlit opencv-python keras xgboost lightgbm
sympy openpyxl xlrd paramiko pexpect colorama tabulate jsonschema regex simplejson ujson orjson msgpack stripe twilio sentry-sdk
langchain tiktoken numba dask pyarrow h5py fsspec s3fs gcsfs google-cloud-storage azure-storage-blob moto responses mock faker
factory-boy hypothesis pytest-cov pytest-mock pytest-asyncio python-dotenv pyjwt bcrypt passlib gevent eventlet websockets tornado
starlette flask-cors flask-sqlalchemy alembic marshmallow pymysql mysqlclient asyncpg kafka-python pika docker kubernetes ansible
fabric invoke pyinstaller cython pybind11 pydantic-core annotated-types sniffio anyio h11 httpcore yarl multidict frozenlist
aiosignal async-timeout pyparsing platformdirs filelock distlib tomli zipp importlib-metadata jmespath s3transfer cachetools rsa
pyasn1 google-auth oauthlib requests-oauthlib pycparser cffi decorator wrapt pygments jedi ipython jupyter notebook pexpect
psutil pyzmq tornado traitlets babel mako itsdangerous blinker gitpython dnspython netaddr scapy shapely pyproj geopandas
statsmodels pytorch-lightning accelerate datasets tokenizers sentencepiece huggingface-hub diffusers gradio pyserial pyusb
""".split())
NPM_POPULAR = set("""react react-dom lodash express axios moment chalk commander debug async request underscore vue typescript
webpack eslint prettier jquery next svelte rxjs uuid dotenv cors body-parser mongoose mysql redis socket.io jest mocha chai sinon
nodemon yargs glob minimist mkdirp rimraf semver inquirer ora colors bluebird cheerio puppeteer playwright tailwindcss postcss
autoprefixer sass vite rollup esbuild classnames prop-types react-router react-router-dom redux react-redux immer zod yup formik
date-fns dayjs node-fetch isomorphic-fetch ws jsonwebtoken bcrypt bcryptjs passport helmet morgan multer sharp pg sequelize knex
typeorm prisma graphql apollo-server nestjs core-js regenerator-runtime tslib @babel/core @types/node @types/react
""".split())

_HOMO = str.maketrans({"0": "o", "1": "l", "5": "s", "3": "e"})


def _norm(n):
    return re.sub(r"[-_.]+", "-", n.lower())


def _dist(a, b, cap=3):
    """Optimal-string-alignment (Damerau-Levenshtein) distance, early exit above cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            if prev2 and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def typosquat_of(name, popular):
    n = _norm(name)
    if n in popular or len(n) < 5:
        return None
    best = None
    for p in popular:
        if abs(len(p) - len(n)) > 2 or p[0] != n[0] and _dist(n, p, 1) > 1:
            continue
        limit = 1 if len(p) < 9 else 2
        d = _dist(n, p, limit)
        if d <= limit and (best is None or d < best[1]):
            best = (p, d)
        if n.translate(_HOMO) == p and n != p:
            best = (p, 1)
    return best


def check_added(path, lines, policy):
    """lines: [(lineno, text)] added lines of a dependency manifest. Returns finding dicts (no severity yet)."""
    out, name = [], path.rsplit("/", 1)[-1].lower()
    if re.fullmatch(r"requirements.*\.txt|constraints.*\.txt", name):
        for ln, raw in lines:
            s = raw.split("#")[0].strip()
            if not s:
                continue
            if re.match(r"--(extra-)?index-url|-i\s", s):
                out.append(dict(line=ln, kind="index", msg="custom package index (dependency-confusion risk)", evidence=s[:90]))
                continue
            if re.match(r"(git\+|https?://|file:)", s) or " @ " in s:
                out.append(dict(line=ln, kind="url", msg="dependency installed from a URL/VCS instead of the package index", evidence=s[:90]))
                continue
            m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", s)
            if m and (t := typosquat_of(m.group(1), PY_POPULAR)):
                out.append(dict(line=ln, kind="typosquat", msg=f"'{m.group(1)}' looks like a typosquat of '{t[0]}' ({t[1]} edit away)", evidence=s[:90]))
    elif name == "package.json":
        for ln, raw in lines:
            m = re.match(r'\s*"([@\w./-]+)"\s*:\s*"([^"]*)"', raw)
            if not m:
                continue
            pkg, ver = m.groups()
            if pkg in ("preinstall", "postinstall", "install"):
                out.append(dict(line=ln, kind="install-script", msg=f"adds an install-time script '{pkg}' (runs on every npm install)", evidence=raw.strip()[:90]))
            elif re.match(r"(git\+|https?:|file:|github:)", ver):
                out.append(dict(line=ln, kind="url", msg=f"'{pkg}' is installed from a URL/VCS", evidence=raw.strip()[:90]))
            elif re.match(r"[\^~<>=*\d]|latest", ver) and (t := typosquat_of(pkg, NPM_POPULAR)):
                out.append(dict(line=ln, kind="typosquat", msg=f"'{pkg}' looks like a typosquat of '{t[0]}' ({t[1]} edit away)", evidence=raw.strip()[:90]))
    return out


def is_manifest(path):
    n = path.rsplit("/", 1)[-1].lower()
    return bool(re.fullmatch(r"requirements.*\.txt|constraints.*\.txt|package\.json", n))
