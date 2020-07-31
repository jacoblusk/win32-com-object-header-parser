import functools
import math
import struct
import ctypes

PyLong_AsByteArray = ctypes.pythonapi._PyLong_AsByteArray
PyLong_AsByteArray.argtypes = [ctypes.py_object,
                               ctypes.c_char_p,
                               ctypes.c_size_t,
                               ctypes.c_int,
                               ctypes.c_int]

def packl_ctypes(lnum):
    a = ctypes.create_string_buffer(lnum.bit_length() // 8 + 1)
    PyLong_AsByteArray(lnum, a, len(a), 0, 1)
    return a.raw

class ParseError(Exception):
    pass

def curried (function):
    argc = function.__code__.co_argcount

    # Pointless to curry a function that can take no arguments
    if argc == 0:
        return function

    from functools import partial
    def func (*args):
        if len(args) >= argc:
            return function(*args)
        else:
            return partial(func, *args)
    return func

def create_parser(func):
    argc = func.__code__.co_argcount
    if argc == 1:
        return Parser(func)

    @functools.wraps(func)
    def _curried(*args, **kwargs):
        return Parser(functools.partial(func, *args, **kwargs))
    return _curried

class Parser:
    def __init__(self, fn):
        self.fn = fn

    def parse(self, target):
        initial_state = ParserState(target, 0, None)
        return self.fn(initial_state)

    def chain(self, chain_fn):
        @create_parser
        def __chain_apply(parser_state):
            next_state = self.fn(parser_state)
            next_parser = chain_fn(next_state.result)
            return next_parser.fn(next_state)
        return __chain_apply

    def map(self, map_fn):
        @create_parser
        def __map_apply(parser_state):
            next_state = self.fn(parser_state)
            return next_state.update(next_state.index, map_fn(next_state.result))
        return __map_apply

    def error_map(self, error_map_fn):
        @create_parser
        def __error_map_apply(parser_state):
            try:
                next_state = self.fn(parser_state)
            except ParseError as parse_error:
                return parser_state.update(parser_state.index,
                                           error_map_fn(parse_error, parser_state.index))
            else:
                return next_state
        return __error_map_apply
        

class ParserState:
    def __init__(self, source, index, result):
        self.source = source
        self.index = index
        self.result = result

    @property
    def target(self):
        return self.source[self.index:]

    def update(self, index, result):
        return ParserState(self.source, index, result)

    def __str__(self):
        return str(vars(self))

@create_parser
def string(target, parser_state):
    if len(target) > len(parser_state.target):
        raise EOFError("End of input reached, unable to match further.")
    
    if parser_state.target.startswith(target):
        return parser_state.update(parser_state.index + len(target), target)
    else:
        raise ParseError(f"\"{parser_state.target[:len(target)]}\" at index "
                         f"{parser_state.index} does not start with \"{target}\".")


@create_parser
def letter(parser_state):
    if len(parser_state.target) == 0:
        raise EOFError("End of input reached, unable to match further.")
    
    if parser_state.target[0].isalpha():
        return parser_state.update(parser_state.index + 1, parser_state.target[0])
    else:
        raise ParseError(f"Couldn't match letters at index {parser_state.index}.")

@create_parser
def digit(parser_state):
    if len(parser_state.target) == 0:
        raise EOFError("End of input reached, unable to match further.")
    
    if parser_state.target[0].isdigit():
        return parser_state.update(parser_state.index + 1, parser_state.target[0])
    else:
        raise ParseError(f"Couldn't match digits at index {parser_state.index}.")

@create_parser
def sequence_of(parsers, parser_state):
    results = []
    for p in parsers:
        parser_state = p.fn(parser_state)
        results.append(parser_state.result)

    return parser_state.update(parser_state.index, results)

@create_parser
def choice(parsers, parser_state):
    for p in parsers:
        try:
            parser_state = p.fn(parser_state)
        except ParseError:
            continue
        else:
            return parser_state

    raise ParseError(f"Unable to match any parsers at index {parser_state.index}.")

@create_parser
def many(parser, parser_state):
    results = []

    try:
        parser_state = parser.fn(parser_state)
        results.append(parser_state.result)
    except:
        return parser_state

    while True:
        try:
            parser_state = parser.fn(parser_state)
            results.append(parser_state.result)
        except (ParseError, EOFError):
            return parser_state.update(parser_state.index, results)

@create_parser
def many1(parser, parser_state):
    results = []

    # Check to see if we match at least one.
    parser_state = parser.fn(parser_state)
    results.append(parser_state.result)

    while True:
        try:
            parser_state = parser.fn(parser_state)
            results.append(parser_state.result)
        except (ParseError, EOFError):
            return parser_state.update(parser_state.index, results)

letters = many1(letter).map(lambda result: ''.join(result))
digits = many1(digit).map(lambda result: ''.join(result))

def lazy(parser_thunk):
    @create_parser
    def _lazy(parser_state):
        parser = parser_thunk()
        return parser.fn(parser_state)
    return _lazy

@curried
def between(left_parser, right_parser, content_parser):
    return sequence_of([left_parser, content_parser, right_parser]).map(lambda results: results[1])

def separated_by(separator_parser):
    @create_parser
    def _separated_by(value_parser, parser_state):
        results = []
        while True:
            try:
                value_state = value_parser.fn(parser_state)
            except ParseError:
                break
            else:
                results.append(value_state.result)
                parser_state = value_state

            try:
                separator_state = separator_parser.fn(parser_state)
            except ParseError:
                break
            else:
                parser_state = separator_state
        return parser_state.update(parser_state.index, results)
    return _separated_by

@create_parser
def succeed(value, parser_state):
    return parser_state.update(parser_state.index, value)

@create_parser
def fail(error_message, parser_state):
    raise ParseError(error_message)

@create_parser
def bit(parser_state):
    byte_offset = math.floor(parser_state.index / 8)
    if byte_offset >= len(parser_state.source):
        raise EOFError("End of input reached, unable to match further.")

    bit_offset = 7 - (parser_state.index % 8)
    byte = parser_state.source[byte_offset]
    bit = (byte & (1 << bit_offset)) >> bit_offset
    return parser_state.update(parser_state.index + 1, bit)

@create_parser
def zero(parser_state):
    byte_offset = math.floor(parser_state.index / 8)
    if byte_offset >= len(parser_state.source):
        raise EOFError("End of input reached, unable to match further.")

    bit_offset = 7 - (parser_state.index % 8)
    byte = parser_state.source[byte_offset]
    bit = (byte & (1 << bit_offset)) >> bit_offset
    if bit != 0:
        raise ParseError(f"Expected a zero, but got a one at index {parser_state.index}")
    return parser_state.update(parser_state.index + 1, bit)

@create_parser
def one(parser_state):
    byte_offset = math.floor(parser_state.index / 8)
    if byte_offset >= len(parser_state.source):
        raise EOFError("End of input reached, unable to match further.")

    bit_offset = 7 - (parser_state.index % 8)
    byte = parser_state.source[byte_offset]
    bit = (byte & (1 << bit_offset)) >> bit_offset
    if bit != 1:
        raise ParseError(f"Expected a one, but got a zero at index {parser_state.index}")
    return parser_state.update(parser_state.index + 1, bit)

def uint(n):
    return sequence_of([bit] * n).map(lambda result: sum(
        map(lambda ix: ix[1] * 2 ** (n - (ix[0] + 1)), enumerate(result))
    ))

def int(n):
    return sequence_of([bit] * n).map(lambda bits: sum(
        map(lambda ix: ix[1] * 2 ** (n - (ix[0] + 1)), enumerate(bits))
    ) if bits[0] == 0 else -(1 + sum(
        map(lambda ix: (0 if ix[1] == 1 else 1) * 2 ** (n - (ix[0] + 1)), enumerate(bits))
    )))

@create_parser
def raw_string(source, parser_state):
    string_source = source.encode('utf-8')
    return sequence_of(
        map(lambda b: uint(8).chain(lambda result:
                succeed(b) if result == b else fail(f'Expected {chr(b)}, but got {chr(result)}.')), string_source)
    ).fn(parser_state)


@curried
def tag(type_, value):
    return (type_, value)

ipv4_header_parser = sequence_of([
    uint(4).map(tag('Version')),
    uint(4).map(tag('IHL')),
    uint(6).map(tag('DSCP')),
    uint(2).map(tag('ECN')),
    uint(16).map(tag('Total Length')),
    uint(16).map(tag('Identification')),
    uint(3).map(tag('Flags')),
    uint(13).map(tag('Fragment Offset')),
    uint(8).map(tag('TTL')),
    uint(8).map(tag('Protocol')),
    uint(16).map(tag('Header Checksum')),
    uint(32).map(lambda result: tag('Source IP', '.'.join(map(str, result.to_bytes(4, 'big'))))),
    uint(32).map(lambda result: tag('Destination IP', '.'.join(map(str, result.to_bytes(4, 'big')))))
]).chain(lambda result:
         sequence_of([uint(8)] * 8).chain(lambda remaining:
                                          succeed(result + list(tag('Options', remaining)))) if result[1][1] > 5 else succeed(result))

with open('packet.bin', 'rb') as f:
    print(ipv4_header_parser.parse(f.read()).result)
