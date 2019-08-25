from collections.abc import Sized
from datetime import datetime, date
import re
from typing import NamedTuple, Set, Iterable, Dict, TypeVar, Callable, List, Optional, Union, Any, Collection, Sequence, Tuple
from pathlib import Path
import itertools
import logging
from functools import lru_cache
import pytz

from .normalise import normalise_url

from kython.ktyping import PathIsh
from kython.kerror import Res, unwrap
from kython.canonify import CanonifyException

import dateparser # type: ignore


Url = str
Source = str
DatetimeIsh = Union[datetime, date, str]
Context = str
Second = int

# TODO hmm. arguably, source and context are almost same things...
class Loc(NamedTuple):
    title: str
    href: Optional[str]=None

    @classmethod
    def make(cls, title: str, href: Optional[str]=None):
        return cls(title=title, href=href)

    @classmethod
    def file(cls, path: PathIsh, line: Optional[int]=None):
        ll = '' if line is None else f':{line}'
        loc = f'{path}{ll}'
        return cls.make(
            title=loc,
            href=f'emacs:{loc}'
        )

    # TODO need some uniform way of string conversion
    # but generally, it would be
    # (url|file)(linenumber|json_path|anchor)


# TODO serialize unions? Might be a bit mad...
# TODO FIXME need to discard cache...
class PreVisit(NamedTuple):
    url: Url
    dt: datetime # TODO FIXME back to DatetimeIsh, but somehow make compatible to dbcache
    locator: Loc
    context: Optional[Context] = None
    duration: Optional[Second] = None
    # TODO shit. I need to insert it in chrome db....
    # TODO gonna be hard to fill retroactively.
    # spent: Optional[Second] = None
    debug: Optional[str] = None


Extraction = Union[PreVisit, Exception]

class DbVisit(NamedTuple):
    norm_url: Url
    orig_url: Url
    dt: datetime
    locator: Loc
    src: Optional[Source] = None
    context: Optional[Context] = None
    duration: Optional[Second] = None

    @staticmethod
    def make(p: PreVisit, src: Source) -> Res['DbVisit']:
        try:
            if isinstance(p.dt, str):
                dt = dateparser.parse(p.dt)
            elif isinstance(p.dt, datetime):
                dt = p.dt
            elif isinstance(p.dt, date):
                dt = datetime.combine(p.dt, datetime.min.time()) # meh..
            else:
                raise AssertionError(f'unexpected date: {p.dt}, {type(p.dt)}')
        except Exception as e:
            return e

        try:
            nurl = normalise_url(p.url)
        except Exception as e:
            return e

        return DbVisit(
            # TODO shit, can't handle errors properly here...
            norm_url=nurl,
            orig_url=p.url,
            dt=dt,
            locator=p.locator,
            context=p.context,
            duration=p.duration,
            src=src,
        )


Filter = Callable[[Url], bool]

def make_filter(thing) -> Filter:
    if isinstance(thing, str):
        rc = re.compile(thing)
        def filter_(u: str) -> bool:
            return rc.search(u) is not None
        return filter_
    else: # must be predicate
        return thing


def get_logger():
    return logging.getLogger("WereYouHere")

# TODO do i really need to inherit this??
class History(Sized):
    # TODO I guess instead filter on DbVisit making site?
    FILTERS: List[Filter] = [
        make_filter(f) for f in
        [
            r'^chrome-devtools://',
            r'^chrome-extension://',
            r'^chrome-error://',
            r'^chrome-native://',
            r'^chrome-search://',

            r'chrome://newtab',
            r'chrome://apps',
            r'chrome://history',

            r'^about:',
            r'^blob:',
            r'^view-source:',

            r'^content:',

            # TODO maybe file:// too?
            # chrome-search:
        ]
    ]

    @classmethod
    def add_filter(cls, filterish):
        cls.FILTERS.append(make_filter(filterish))

    def __init__(self, *, src: Source):
        self.vmap: Dict[PreVisit, DbVisit] = {}
        # TODO err... why does it map from previsit???
        self.logger = get_logger()
        self.src = src

    # TODO mm. maybe history should get filters from some global config?
    # wonder how okay is it to set class attribute..

    @classmethod
    def filtered(cls, url: Url) -> bool:
        for f in cls.FILTERS:
            if f(url):
                return True
        return False

    @property
    def visits(self) -> List[DbVisit]:
        return list(self.vmap.values())

    def register(self, v: PreVisit) -> Optional[Exception]:
        # TODO should we filter before normalising? not sure...
        if History.filtered(v.url):
            return None

        # TODO perhaps take normalised into account here??
        if v in self.vmap:
            return None

        try:
            # TODO if we do it as unwrap(DbVisit.make, v), then we can access make return type and properly handle error type?
            # TODO tag needs to go here??
            db_visit = unwrap(DbVisit.make(v, src=self.src))
        except CanonifyException as ce:
            self.logger.error('error while canonnifying %s... ignoring', v)
            self.logger.exception(ce)
            return None
        except Exception as e:
            return e

        self.vmap[v] = db_visit
        return None
        # TODO hmm some filters make sense before stripping off protocol...

    ## only used in tests?..
    def _nmap(self):
        from kython import group_by_key
        return group_by_key(self.visits, key=lambda x: x.norm_url)

    def __len__(self) -> int:
        return len(self._nmap())

    def __contains__(self, url) -> bool:
        return url in self._nmap()

    def __getitem__(self, url: Url):
        return self._nmap()[url]
    #

    def __repr__(self):
        return 'History{' + repr(self.visits) + '}'


# kinda singleton
@lru_cache(1)
def get_tmpdir():
    import tempfile
    tdir = tempfile.TemporaryDirectory(suffix="wereyouhere")
    return tdir

@lru_cache(1)
def _get_extractor():
    from urlextract import URLExtract # type: ignore
    u = URLExtract()
    # https://github.com/lipoja/URLExtract/issues/13
    # u._stop_chars_right |= {','}
    # u._stop_chars_left  |= {','}
    return u


def sanitize(url: str) -> str:
    # TODO not sure it's a really good idea.. but seems easiest now
    # TODO have whitelisted urls that allow trailing parens??
    url = url.strip(',.…\\')
    if 'wikipedia' not in url:
        # urls might end with parens en.wikipedia.org/wiki/Widget_(beer)
        url = url.strip(')')
    return url


# TODO sort just in case? not sure..
def _extract_urls(s: str) -> List[str]:
    # TODO unit test for escaped urls.. or should it be in normalise instead?
    if len(s.strip()) == 0:
        return [] # optimize just in case..

    # TODO special handling for org links

    # TODO fuck. doesn't look like it's handling multiple urls in same line well...
    # ("python.org/one.html python.org/two.html",
    # hopefully ok... I guess if there are spaces in url we are fucked anyway..
    extractor = _get_extractor()
    urls: List[str] = []
    for x in s.split():
        urls.extend(extractor.find_urls(x))

    return [sanitize(u) for u in urls]


def extract_urls(s: str) -> List[str]:
    return list(itertools.chain.from_iterable(map(_extract_urls, s.splitlines())))


def from_epoch(ts: int) -> datetime:
    res = datetime.utcfromtimestamp(ts)
    res.replace(tzinfo=pytz.utc)
    return res


# TODO kythonize?
class PathWithMtime(NamedTuple):
    path: Path
    mtime: float

    @classmethod
    def make(cls, p: Path):
        return cls(
            path=p,
            mtime=p.stat().st_mtime,
        )


class Indexer:
    def __init__(self, ff, *args, src: str, **kwargs):
        self.ff = ff
        self.args = args
        self.kwargs = kwargs
        self.src = src


# TODO do we really need it?
def previsits_to_history(extractor, *, src: Source) -> Tuple[List[DbVisit], List[Exception]]:
    ex = extractor
    # TODO isinstance wrapper?
    # TODO make more defensive?
    logger = get_logger()

    log_info: str
    if isinstance(ex, Indexer):
        log_info = f'{ex.ff.__module__}:{ex.ff.__name__} {ex.args} {ex.kwargs} ...'
        extr = lambda: ex.ff(*ex.args, **ex.kwargs)
    else:
        # TODO if it's a lambda?
        log_info = f'{ex.__module__}:{ex.__name__}'
        extr = ex


    logger.info('extracting via %s ...', log_info)

    h = History(src=src)
    errors = []
    previsits = list(extr()) # TODO DEFENSIVE HERE!!!
    for p in previsits:
        if isinstance(p, Exception):
            errors.append(p)

            # Ok, I guess we can't rely on normal exception logger here because it expects proper traceback
            # so we can unroll the cause chain manually at least...
            # TODO at least preserving location would be nice.
            parts = ['indexer emitted exception']
            cur: Optional[BaseException] = p
            while cur is not None:
                ss = str(cur)
                if len(parts) >= 2:
                    ss = 'caused by ' + ss # TODO use some lib for that
                parts.append(ss)
                cur = cur.__cause__
            logger.error('\n'.join(parts))
            continue

        # TODO check whether it's filtered before construction? probably doesn't really impact
        try:
            unwrap(h.register(p))
        except Exception as e:
            logger.exception(e)
            errors.append(e)

    # TODO should handle filtering properly?
    logger.info('extracting via %s: got %d visits', log_info, len(h))
    return h.visits, errors
