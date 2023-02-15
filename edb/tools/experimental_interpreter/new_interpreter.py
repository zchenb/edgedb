


from .data.data_ops import *
from .helper_funcs import *
import sys
import traceback
from edb.edgeql import ast as qlast
from edb import edgeql
import pprint
from .data.built_in_ops import all_builtin_funcs
from edb.common import debug
from .elaboration import *


from .evaluation import *
from .back_to_ql import reverse_elab
from .data.path_factor import select_hoist
import copy

def run_statement(db : DB, stmt : qlast.Expr, dbschema : DBSchema, should_print : bool) -> Tuple[MultiSetVal, DB]:
    if should_print:
        print("vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv Starting")
        debug.dump_edgeql(stmt)
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Elaborating")

    elaborated = elab(stmt)

    if should_print:
        debug.print(elaborated)
        # debug.dump(reverse_elab(elaborated))
        debug.dump_edgeql(reverse_elab(elaborated))
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Preprocessing")

    factored = select_hoist(elaborated, dbschema)

    if should_print:
        debug.print(factored)
        # debug.dump(reverse_elab(factored))
        debug.dump_edgeql(reverse_elab(factored))
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Running")

    config = RTExpr(
            RTData(DB(db.dbdata), 
                [DB({**db.dbdata})],
                dbschema,
                False
            ), factored)
    result = eval_config(config)
    if should_print:
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Result")
        debug.print(result.val)
        print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ Done ")
    return (result.val, result.data.cur_db)
    # debug.dump(stmt)

def run_stmts (db : DB, stmts : List[qlast.Expr],dbschema : DBSchema, debug_print : bool) -> Tuple[List[MultiSetVal], DB]:
    match stmts:
        case []:
            return ([], db)
        case current, *rest:
            (cur_val, next_db) = run_statement(db, current, dbschema, should_print=debug_print)
            (rest_val, final_db) = run_stmts(next_db, rest, dbschema, debug_print)
            return ([cur_val, *rest_val], final_db)
    raise ValueError("Not Possible")

def run_str(
    db: DB,
    s: str,
    print_asts: bool = False
) -> Tuple[List[MultiSetVal], DB]:
    q = parse(s)
    # if print_asts:
    #     debug.dump(q)
    (res, next_db) = run_stmts(db, q, DBSchema({}, all_builtin_funcs), print_asts)
    # if output_mode == 'pprint':
    #     pprint.pprint(res)
    # elif output_mode == 'json':
    #     print(EdbJSONEncoder().encode(res))
    # elif output_mode == 'debug':
    #     debug.dump(res)
    return (res, next_db)

def run_single_str(
    db: DB,
    s: str,
    print_asts: bool = False
) -> Tuple[MultiSetVal, DB]:
    q = parse(s)
    if len(q) != 1:
        raise ValueError("Not a single query")
    (res, next_db) = run_statement(db, q[0], DBSchema({}, all_builtin_funcs), print_asts)
    return (res, next_db)


def repl(*, init_ql_file = None, debug_print=False) -> None:
    # for now users should just invoke this script with rlwrap since I
    # don't want to fiddle with history or anything
    db = empty_db()
    if init_ql_file is not None:
        initial_queries = open(init_ql_file).read()
        db = run_str(db, initial_queries, print_asts=debug_print)
    while True:
        print("> ", end="", flush=True)
        s = ""
        while ';' not in s:
            s += sys.stdin.readline()
            if not s:
                return
        try:
            (_, db) = run_str(db, s, print_asts=debug_print)
        except Exception:
            traceback.print_exception(*sys.exc_info())

def db_with_initilial_queries(initial_queries : str, debug_print=False) -> DB:
    db = empty_db()
    (_, db) = run_str(db, initial_queries, print_asts=debug_print)
    return db


if __name__ == "__main__":
    repl()