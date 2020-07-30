from collections.abc import Iterable
import enum
import string

class PatternMatchType(enum.Enum):
    ANY = enum.auto()
    UNTIL = enum.auto()

class TokenType(enum.Enum):
    IDENTIFIER = enum.auto()
    SYMBOL = enum.auto()

class LexerError(Exception):
    pass

class Lexer:
    def __init__(self, text):
        self.text = text
        self.index = 0

    def __iter__(self):
        while self.index < len(self.text):
            character = self.text[self.index]
            if character.isspace():
                self.increment()
            elif character in string.punctuation:
                yield self.lex_symbol()
            elif character.isalpha():
                yield self.lex_identifier()
            elif character.isdigit():
                self.increment()
            else:
                raise LexerError(f"Unknown character {character} found.")

    def increment(self, amount=1):
        self.index += amount

    def lex_identifier(self):
        end_index = self.index + 1
        while end_index < len(self.text):
            character = self.text[end_index]
            if (character in string.punctuation and character != '_') \
               or character.isspace():
                break
            end_index += 1

        lexeme = self.text[self.index:end_index]
        self.increment(amount=len(lexeme))
        return (TokenType.IDENTIFIER, lexeme)

    def lex_number(self):
        self.increment()

    def lex_symbol(self):
        lexeme = self.text[self.index]
        self.increment()
        return (TokenType.SYMBOL, lexeme)

COMMENT_PATTERN = ([
    (TokenType.SYMBOL, '/'),
    (TokenType.SYMBOL, '*'),
    (PatternMatchType.UNTIL, 2),
    (TokenType.SYMBOL, '*'),
    (TokenType.SYMBOL, '/')
], 'COMMENT')

METHOD_PATTERN = ([
    (TokenType.IDENTIFIER, ['STDMETHOD', 'STDMETHOD_']),
    (TokenType.SYMBOL, '('),
    (PatternMatchType.UNTIL, 1),
    (TokenType.SYMBOL, ')'),
    (TokenType.SYMBOL, '('),
    (PatternMatchType.UNTIL, 1),
    (TokenType.SYMBOL, ')')
], 'METHOD')

INTERFACE_PATTERN = ([
    (TokenType.IDENTIFIER, 'DECLARE_INTERFACE_'),
    (TokenType.SYMBOL, '('),
    (PatternMatchType.UNTIL, 1),
    (TokenType.SYMBOL, ')')
], 'INTERFACE')

class PatternMatcher:
    def __init__(self, patterns):
        self.patterns = patterns

    def register_pattern(self, pattern):
        pattern.append(pattern)

    def match_tokens(self, tokens):
        i = 0

        groups = []
        token_length = len(tokens)
        while i < token_length:
            result = self.try_match(tokens[i:])
            if result:
                tokens_pattern, _ = result
                i += len(tokens_pattern)
                groups.append(result)
            else:
                i += 1
        return groups
            
    def try_match_pattern(self, tokens_slice, pattern):
        pattern_list, pattern_name = pattern
        pattern_match_until_index = 0
        pattern_match_until_sequnce = None
        pattern_index = 0
        token_index = 0
        while token_index < len(tokens_slice) and pattern_index < len(pattern_list):
            token_type, lexeme = tokens_slice[token_index]
            pattern_match_type, pattern_match_arg = pattern_list[pattern_index]
            if isinstance(pattern_match_type, TokenType):
                if isinstance(pattern_match_arg, list):
                    if lexeme in pattern_match_arg:
                        pattern_index += 1
                        token_index += 1
                    else:
                        return None
                else:
                    if lexeme == pattern_match_arg:
                        pattern_index += 1
                        token_index += 1
                    else:
                        return None
            elif isinstance(pattern_match_type, PatternMatchType):
                if pattern_match_type == PatternMatchType.ANY:
                    token += 1
                    pattern_index += 1
                elif pattern_match_type == PatternMatchType.UNTIL:
                    if pattern_match_until_sequnce is None:
                        pattern_match_until_sequnce = pattern_list[pattern_index + 1:pattern_index + 1 + pattern_match_arg]
                        token_index += 1
                    else:
                        if lexeme == pattern_match_until_sequnce[pattern_match_until_index][1]:
                            pattern_match_until_index += 1
                        if pattern_match_until_index >= len(pattern_match_until_sequnce):
                            pattern_match_until_sequence = None
                            pattern_match_until_index = 0
                            pattern_index += 1 + pattern_match_arg
                        token_index += 1
                else:
                    return None
        return tokens_slice[:token_index], pattern_name
            
    def try_match(self, tokens_slice):
        for pattern in self.patterns:
            result = self.try_match_pattern(tokens_slice, pattern)
            if result:
                return result
        return None
            
def parse_structures(pattern_matcher_result):
    structures = []
    current_struct_name = None
    struct_start_index = 0
    i = 0
    while i < len(pattern_matcher_result):
        pattern_tokens, pattern_name = pattern_matcher_result[i]
        if pattern_name == "INTERFACE":
            if current_struct_name != None:
                structures.append((pattern_matcher_result[struct_start_index + 1: i], current_struct_name))
            struct_start_index = i
            _, current_struct_name = pattern_tokens[2]
        i += 1
    structures.append((pattern_matcher_result[struct_start_index + 1: i], current_struct_name))
    return structures

class MethodParseState(enum.Enum):
    PARSE_START = enum.auto()
    PARSE_NAME = enum.auto()
    PARSE_OPEN_PAREN = enum.auto()
    PARSE_CLOSED_PAREN = enum.auto()
    PARSE_RETURN_TYPE = enum.auto()
    PARSE_ARGUMENTS = enum.auto()
    PARSE_END = enum.auto()


structure_prologue_template = """class $CLASS_NAME(ctypes.Structure):
    _fields_ = [
"""
fnptr_templay = "${CLASS_NAME}_${METHOD_NAME}Type = ctypes.WINFUNCTYPE($RETURN_TYPE$ARGS)"
method_template = "        ('$METHOD_NAME', ${CLASS_NAME}_${METHOD_NAME}Type),"
structure_epilogue = """
    ]
"""

def parse_arguments(arguments_tokens):
    arguments = []
    type_builder = ""
    argument_name = None
    for token_type, lexeme in arguments_tokens:
        if lexeme == ',':
            arguments.append((argument_name, type_builder))
            argument_name = None
            type_builder = ""
        elif len(type_builder) == 0 and token_type == TokenType.IDENTIFIER:
            type_builder += lexeme
        elif len(type_builder) > 0 and token_type == TokenType.SYMBOL:
            type_builder += lexeme
        elif token_type == TokenType.IDENTIFIER:
            argument_name = lexeme
    if argument_name != None:
        arguments.append((argument_name, type_builder))
    return arguments

def parse_method(pattern_tokens):
    method_name = None
    method_types = []
    method_args_tokens = []
    method_return_value = None
    
    parse_method_state = MethodParseState.PARSE_START
    for token_type, lexeme in pattern_tokens:
        if parse_method_state == MethodParseState.PARSE_START:
            if lexeme == "STDMETHOD":
                method_return_value = "HRESULT"
                parse_method_state = MethodParseState.PARSE_NAME
            else:
                parse_method_state = MethodParseState.PARSE_RETURN_TYPE
        elif parse_method_state == MethodParseState.PARSE_NAME:
            if token_type == TokenType.IDENTIFIER:
                method_name = lexeme
                parse_method_state = MethodParseState.PARSE_CLOSED_PAREN
        elif parse_method_state == MethodParseState.PARSE_CLOSED_PAREN:
            if lexeme == ')':
                parse_method_state = MethodParseState.PARSE_ARGUMENTS
        elif parse_method_state == MethodParseState.PARSE_RETURN_TYPE:
            if token_type == TokenType.IDENTIFIER:
                method_return_value = lexeme
                parse_method_state = MethodParseState.PARSE_NAME
        elif parse_method_state == MethodParseState.PARSE_ARGUMENTS:
            if lexeme == ')':
                return (method_name, method_return_value, parse_arguments(method_args_tokens))
            if lexeme != '(' and lexeme != ')' and "THIS" not in lexeme and lexeme != "CONST":
                method_args_tokens.append((token_type, lexeme))
    return None

def convert_pointer(type_):
    pointer_count = type_.count('*')
    if pointer_count == 0:
        return type_

    pointer_type = ""
    for i in range(pointer_count):
        pointer_type += 'ctypes.POINTER('
    pointer_type += type_.strip('*')
    pointer_type += ')' * pointer_count
    return pointer_type
        

if __name__ == "__main__":
    with open('d3d9.h', mode='r') as f:
        text = f.read() 
    tokens = list(token for token in Lexer(text))
    pattern_matcher = PatternMatcher([COMMENT_PATTERN, METHOD_PATTERN, INTERFACE_PATTERN])
    pattern_matcher_result = pattern_matcher.match_tokens(tokens)
    parsed_structures_result = parse_structures(pattern_matcher_result)
    for pattern_matcher_results, structure_name in parsed_structures_result:
        struct_builder = string.Template(structure_prologue_template) \
                               .substitute(CLASS_NAME=structure_name + 'VirtualTable')
        fields = []
        function_type_definitions = []
        for pattern in pattern_matcher_results:
            pattern_tokens, pattern_name = pattern
            if pattern_name == 'METHOD':
                method_name, return_type, arguments = parse_method(pattern_tokens)
                arguments = list(convert_pointer(type_) for _, type_ in arguments)
                
                function_type_definitions.append(string.Template(fnptr_templay) \
                                                       .substitute(
                                                                   CLASS_NAME=structure_name,
                                                                   METHOD_NAME=method_name,
                                                                   RETURN_TYPE=return_type,
                                                                   ARGS=(', ' + ', '.join(arguments)) if len(arguments) > 0 else ''))
                fields.append(string.Template(method_template) \
                                    .substitute(CLASS_NAME=structure_name, METHOD_NAME=method_name))
        struct_builder += '\n'.join(fields)
        struct_builder += structure_epilogue
        struct_builder = '\n' + '\n'.join(function_type_definitions) + '\n\n' + struct_builder
        print(struct_builder)
        
            
