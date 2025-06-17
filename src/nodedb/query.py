import re

# Operators and parentheses only — keep field/regex together in parser phase
# Also, ordering of the regex matters when compiling the token_re
TOKEN_REGEX = [
    ("SKIP", r"\s+"),
    ("OR", r"\|\|"),
    ("AND", r"&"),
    ("NEQ", r"!="),
    ("EQ", r"="),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("IDENT", r"[a-zA-Z_][\w]*"),  # field name
    ("LITERAL", r"(?:[^&|()]+|\([^\)]+\))+"),      # regex literal; more greedy for now
]

token_re = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_REGEX))


def smart_tokenize(query: str):
    tokens = []
    pos = 0
    while pos < len(query):
        match = token_re.match(query, pos)
        if not match:
            raise SyntaxError(f"Unexpected character at position {pos}: `{query[pos:]}` — Verify your syntax.")
        kind = match.lastgroup
        value = match.group()

        if kind == "SKIP":
            pos = match.end()
            continue

        # If IDENT followed by EQ or NEQ, capture entire RHS as LITERAL
        if kind == "IDENT":
            lookahead = token_re.match(query, match.end())
            if lookahead and lookahead.lastgroup in ("EQ", "NEQ"):
                field = value
                op = lookahead.group()
                pos = lookahead.end()
                # Capture the RHS; up to next top-level & || or unmatched RPAREN
                rhs_start = pos
                depth = 0
                while pos < len(query):
                    char = query[pos]
                    if char == '(':
                        depth += 1
                    elif char == ')':
                        if depth == 0:
                            break
                        depth -= 1
                    elif query[pos:pos+2] == '||' and depth == 0:
                        break
                    elif char == '&' and depth == 0:
                        break
                    pos += 1
                pattern = query[rhs_start:pos].strip()
                tokens.append(("IDENT", field))
                tokens.append(("EQ" if op == "=" else "NEQ", op))
                tokens.append(("LITERAL", pattern))
                continue

        tokens.append((kind, value))
        pos = match.end()
    return tokens

def parse_match(tokens, i):
    if tokens[i][0] != "IDENT":
        raise SyntaxError(f"Expected field name but got '{tokens[i][1]}' ({tokens[i][0]}) at position {i}")
    field = tokens[i][1]

    if tokens[i+1][0] not in ("EQ", "NEQ"):
        raise SyntaxError("Expected = or !=")
    op = tokens[i+1][1]

    pattern_parts = []
    j = i + 2
    while j < len(tokens) and tokens[j][0] not in ("AND", "OR", "RPAREN"):
        pattern_parts.append(tokens[j][1])
        j += 1
    pattern = "".join(pattern_parts).strip()
    return ("MATCH", field, op, pattern), j

def parse_expr(tokens, i=0):
    def parse_atom(tokens, i):
        if i >= len(tokens):
            raise SyntaxError("Unexpected end of input")

        tok = tokens[i]

        if tok[0] == "LPAREN":
            node, i = parse_expr(tokens, i + 1)

            if i >= len(tokens):
                raise SyntaxError("Unclosed parenthesis. Expected ')' before end of input")

            if tokens[i][0] != "RPAREN":
                raise SyntaxError(f"Expected ')', got {tokens[i]} at position {i}") 
            return node, i + 1

        elif tok[0] == "IDENT":
            return parse_match(tokens, i)

        else:
            raise SyntaxError(f"Unexpected token '{tok[1]}' ({tok[0]}) at position {i} — expected field or '('")

    def parse_binop(precedence, left, tokens, i):
        while i < len(tokens):
            tok = tokens[i]
            if tok[0] == "RPAREN":
                break

            if tok[0] not in ("AND", "OR"):
                break

            curr_prec = {"OR": 1, "AND": 2}[tok[0]]
            if curr_prec < precedence:
                break

            op = tok[0].lower()
            i += 1

            if i >= len(tokens):
                raise SyntaxError(f"Operator '{op.upper()}' must be followed by a field expression, but input ended")

            right, i = parse_atom(tokens, i)

            # Check for more tightly bound ops
            while i < len(tokens):
                if tokens[i][0] in ("AND", "OR"):
                    next_prec = {"OR": 1, "AND": 2}[tokens[i][0]]
                    if next_prec > curr_prec:
                        right, i = parse_binop(next_prec, right, tokens, i)
                    else:
                        break
                else:
                    break

            left = (op, left, right)

        return left, i


    left, i = parse_atom(tokens, i)
    return parse_binop(0, left, tokens, i)