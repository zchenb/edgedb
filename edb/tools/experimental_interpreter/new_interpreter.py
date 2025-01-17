
import signal

import json
import sys
import traceback
import os
from typing import *
from typing import Tuple
import readline

from edb.common import debug
from edb.edgeql import ast as qlast

from .type_checking_tools import typechecking as tc
from .back_to_ql import reverse_elab
# from .basis.built_ins import all_builtin_funcs
from .data import data_ops as e
from .data import expr_ops as eops
from .data.data_ops import DB, DBSchema, MultiSetVal, ResultTp
from .data.data_ops import *
from .data.expr_to_str import show_expr, show_result_tp, show_schema
from .data.path_factor import select_hoist
from .data.deduplicaiton_insert import insert_conditional_dedup
from .data.val_to_json import (json_like, multi_set_val_to_json_like,
                               typed_multi_set_val_to_json_like)
from .elab_schema import add_module_from_sdl_defs, add_module_from_sdl_file
from .elaboration import elab
from .evaluation import RTExpr, eval_expr_toplevel
from .helper_funcs import parse_ql
from .logs import write_logs_to_file
from .sqlite import sqlite_adapter
from .data import expr_to_str as pp
from .db_interface import *
from .schema.library_discovery import *
from .type_checking_tools import schema_checking as sck
# CODE REVIEW: !!! CHECK IF THIS WILL BE SET ON EVERY RUN!!!
# sys.setrecursionlimit(10000)




def empty_db(schema : DBSchema) -> EdgeDatabaseInterface:
    return InMemoryEdgeDatabase(schema)

def empty_dbschema() -> DBSchema:
    return DBSchema({}, {}, {}, {}, {})

def default_dbschema() -> DBSchema:
    initial_db = empty_dbschema()
    relative_path_to_std = os.path.join("..", "..", "lib", "std")
    relative_path_to_schema = os.path.join("..", "..", "lib", "schema.edgeql")
    std_path = os.path.join(os.path.dirname(__file__), relative_path_to_std)
    schema_path = os.path.join(os.path.dirname(__file__), relative_path_to_schema)
    print("Loading standard library at", std_path)
    add_ddl_library(
        initial_db,
        [std_path, schema_path]
    )
    sck.re_populate_module_inheritance(initial_db, ("std",))
    sck.re_populate_module_inheritance(initial_db, ("schema",))
    print("=== Standard library loaded ====")
    return initial_db

    # return DBSchema({("std",): DBModule({k: e.ModuleEntityFuncDef(v) for (k,v) in all_builtin_funcs.items()})},{})




def run_statement(db: EdgeDatabaseInterface,
                  stmt: qlast.Expr, dbschema: DBSchema,
                  should_print: bool,
                  logs: Optional[List[Any]],
                  skip_type_checking: bool = False,
                  ) -> Tuple[MultiSetVal, e.ResultTp]:

    dbschema_ctx = e.TcCtx(dbschema, ("default",), {})

    if should_print:
        print("vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv Starting")
        debug.dump_edgeql(stmt)
        # debug.print("Schema: " + show_schema(dbschema))
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Elaborating")

    elaborated = elab(stmt)

    if should_print:
        debug.print(show_expr(elaborated))
        # debug.dump(reverse_elab(elaborated))
        debug.dump_edgeql(reverse_elab(elaborated))
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Preprocessing")

    factored = select_hoist(elaborated, dbschema_ctx)

    if should_print:
        debug.print(show_expr(factored))
        reverse_elabed = reverse_elab(factored)
        debug.dump_edgeql(reverse_elabed)

    if skip_type_checking:
        if should_print:
            print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Running")
        result = eval_expr_toplevel(db, factored, logs=logs)
        if should_print:
            print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Result")
            debug.print(result)
            print(multi_set_val_to_json_like((result)))
            print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ Done ")
        return (result, ResultTp(e.NamedNominalLinkTp("NOT AVAILABLE", linkprop=e.ObjectTp({})), CardAny))

    elif should_print:
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Type Checking")

    tp, type_checked = tc.synthesize_type(dbschema_ctx, factored)

    if should_print:
        debug.print(show_result_tp(tp))
        reverse_elabed = reverse_elab(type_checked)
        debug.dump_edgeql(reverse_elabed)
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Deduplicating")


    deduped = insert_conditional_dedup(type_checked)

    if should_print:
        debug.print(pp.show(deduped))
        reverse_elabed = reverse_elab(deduped)
        debug.dump_edgeql(reverse_elabed)
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Running")

    result = eval_expr_toplevel(db, deduped, logs=logs)
    if should_print:
        print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> Result")
        debug.print(pp.show_multiset_val(result))
        # print(typed_multi_set_val_to_json_like(
        #     tp, eops.assume_link_target(result), dbschema))
        print(typed_multi_set_val_to_json_like(tp, result, dbschema))
        print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ Done ")
    return (result, tp)
    # debug.dump(stmt)


def run_stmts(db: EdgeDatabaseInterface, stmts: Sequence[qlast.Expr],
              dbschema: DBSchema, debug_print: bool,
              logs: Optional[List[Any]],
              skip_type_checking: bool = False,
              ) -> Sequence[MultiSetVal]:
    match stmts:
        case []:
            return []
        case current, *rest:
            (cur_val, _) = run_statement(
                db, current, dbschema, should_print=debug_print,
                logs=logs, skip_type_checking=skip_type_checking)
            rest_val = run_stmts(
                db, rest, dbschema, debug_print,
                logs=logs, skip_type_checking=skip_type_checking)
            return [cur_val, *rest_val]
    raise ValueError("Not Possible")

def run_meta_cmd(db: EdgeDatabaseInterface, dbschema: DBSchema, cmd: str) -> MultiSetVal:
    if cmd == "\ps":
        print(pp.show_module(dbschema.modules[("default",)]) + "\n")
    elif cmd == "\ps --all":
        print(pp.show_schema(dbschema) + "\n")
    else:
        raise ValueError("Unknown meta command: " + cmd)

def run_str(
    db: EdgeDatabaseInterface,
    dbschema: DBSchema,
    s: str,
    print_asts: bool = False,
    logs: Optional[List[str]] = None,
    skip_type_checking: bool = False,
) -> Sequence[MultiSetVal]:

    q = parse_ql(s)
    # if print_asts:
    #     debug.dump(q)
    res = run_stmts(db, q, dbschema, print_asts, logs, skip_type_checking=skip_type_checking)
    # if output_mode == 'pprint':
    #     pprint.pprint(res)
    # elif output_mode == 'json':
    #     print(EdbJSONEncoder().encode(res))
    # elif output_mode == 'debug':
    #     debug.dump(res)
    return res


def run_single_str(
    dbschema_and_db: Tuple[DBSchema, EdgeDatabaseInterface],
    s: str,
    print_asts: bool = False
) -> Tuple[MultiSetVal, ResultTp]:
    q = parse_ql(s)
    if len(q) != 1:
        raise ValueError("Not a single query")
    dbschema, db = dbschema_and_db
    (res, tp) = run_statement(
        db, q[0], dbschema, print_asts,
        logs=None)
    return (res, tp)


def run_single_str_get_json(
    dbschema_and_db: Tuple[DBSchema, EdgeDatabaseInterface],
    s: str,
    print_asts: bool = False
) -> json_like:
    (res, tp) = run_single_str(dbschema_and_db,
                                        s, print_asts=print_asts)
    return typed_multi_set_val_to_json_like(
                tp, res, dbschema_and_db[0], top_level=True)


def repl(*, init_sdl_file=None,
         init_ql_file=None,
         next_ql_file=None,
         library_ddl_files=None,
         debug_print=False,
         trace_to_file_path=None,
         sqlite_file=None,
         skip_type_checking=False,
         ) -> None:
    # if init_sdl_file is not None and read_sqlite_file is not None:
    #     raise ValueError("Init SDL file and Read SQLite file cannot"
    #                      " be specified at the same time")
    from edb.edgeql import parser as ql_parser
    ql_parser.preload_spec()

    dbschema: DBSchema 
    db: EdgeDatabaseInterface
    logs: List[Any] = []  # type: ignore[var]

    dbschema = default_dbschema()
    if library_ddl_files:
        add_ddl_library(dbschema, library_ddl_files)



    if sqlite_file is not None:
        if init_sdl_file is not None:
            with open(init_sdl_file) as f:
                init_sdl_file_content = f.read()
        else:
            init_sdl_file_content = None
        (dbschema, db) = sqlite_adapter.schema_and_db_from_sqlite(init_sdl_file_content, sqlite_file)
    else:
        if init_sdl_file is not None:
            dbschema = add_module_from_sdl_file(dbschema, init_sdl_file_path=init_sdl_file)
        else:
            dbschema = dbschema
        db = empty_db(dbschema)

    if debug_print:
        print("=== ALL Schema Loaded ===")
        print(pp.show_module(dbschema.modules[("default",)]))

    if init_ql_file is not None:
        initial_queries = open(init_ql_file).read()
        run_str(db, dbschema, initial_queries,
                          print_asts=debug_print, logs=logs)


    try:
        if next_ql_file is not None:
            next_queries = open(next_ql_file).read()
            run_str(db, dbschema, next_queries,
                            print_asts=debug_print, logs=logs)
    except Exception:
        traceback.print_exception(*sys.exc_info())

    history_file = ".edgeql_interpreter_history.temp.txt"
    try:
        readline.read_history_file(history_file)
    except FileNotFoundError:
        pass

    while True:
        if trace_to_file_path is not None:
            write_logs_to_file(logs, trace_to_file_path)
        s = ""
        def reset_s():
            nonlocal s
            print("\nKeyboard Interrupt")
            s = ""
        # signal.signal( signal.SIGINT, lambda s, f : reset_s())
        while ';' not in s and not s.startswith("\\"):
            # s += sys.stdin.readline()
            if s:
                try:
                    s += input("... ")
                except KeyboardInterrupt:
                    reset_s()
                    continue
            else:
                try:
                    s += input("> ")
                except KeyboardInterrupt:
                    reset_s()
                    continue
        try:
            readline.write_history_file(history_file)
            if s.startswith("\\"):
                run_meta_cmd(db, dbschema, s)
            else:
                res = run_str(db, dbschema, s, print_asts=debug_print,
                                    logs=logs, skip_type_checking=skip_type_checking)
                # print("\n".join(json.dumps(multi_set_val_to_json_like(v))
                #                 for v in res))
        except Exception:
            traceback.print_exception(*sys.exc_info())
        


def dbschema_and_db_with_initial_schema_and_queries(
        initial_schema_defs: str,
        initial_queries: str,
        sqlite_file_name: Optional[str] = None,
        debug_print=False,
        logs: Optional[List[Any]] = None) -> Tuple[DBSchema, EdgeDatabaseInterface]:
    if sqlite_file_name is not None:
        dbschema, db = sqlite_adapter.schema_and_db_from_sqlite(initial_schema_defs, sqlite_file_name)
    else:
        dbschema = add_module_from_sdl_defs(default_dbschema(), initial_schema_defs)
        db = empty_db(dbschema)
    run_str(db, dbschema, initial_queries,
                      print_asts=debug_print, logs=logs)
    return dbschema, db


if __name__ == "__main__":
    repl()
