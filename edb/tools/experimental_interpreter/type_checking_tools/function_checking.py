
from ..data import data_ops as e
from ..data import expr_ops as eops
from ..data import type_ops as tops
from ..data import path_factor as pops
from ..data import expr_to_str as pp
from ..data import module_ops as mops
from ..interpreter_logging import print_warning
from typing import List, Tuple, Dict, Optional, Sequence
# from itertools import *
from functools import reduce
import operator
from edb.common import debug
from ..data import expr_to_str as pp


def refine_candidate_tp(tp : e.Tp) -> e.Tp:
    match tp:
        case e.NamedNominalLinkTp(name=name, linkprop=lp):
            return e.NamedNominalLinkTp(name=name, linkprop=e.ObjectTp({}))
        case e.NominalLinkTp(subject=subject, name=name, linkprop=lp):
            # refine also drops subject which may contain additional properties
            return e.NamedNominalLinkTp(name=name, linkprop=e.ObjectTp({}))
        case e.UnionTp(l, r):
            return e.UnionTp(refine_candidate_tp(l), refine_candidate_tp(r))
        case e.IntersectTp(l, r):
            return e.IntersectTp(refine_candidate_tp(l), refine_candidate_tp(r))
        case _:
            return tp

def try_match_and_get_arg_mods(expr: e.FunAppExpr, fun_def: e.FuncDef) -> Optional[Sequence[e.ParamModifier]]:
    """
    Returns None if the expr does not match the fun_def.
    """
    match expr:
        case e.FunAppExpr(fun=fname, args=args, overloading_index=idx, kwargs=kwargs):
            # positional
            if len(args) == len(fun_def.tp.args_mod):
                return fun_def.tp.args_mod
            elif len(args) < len(fun_def.tp.args_mod):
                part_one = fun_def.tp.args_mod[0:len(args)]
                assert(all([fun_def.tp.args_label.index(l) >= len(args) for l in kwargs.keys()]))
                part_two = [fun_def.tp.args_mod[fun_def.tp.args_label.index(l)] for l in kwargs.keys()]
                return [*part_one, *part_two]
            elif len(args) > len(fun_def.tp.args_mod):
                return None
            else:
                raise ValueError("impossible", expr)
        case _:
            raise ValueError("impossible", expr)

def check_args_ret_type_match(ctx : e.TcCtx, tps_syn: List[e.Tp], tps_ck: e.FunArgRetType) -> Optional[e.Tp]: # Returns the result Tp if matches
    """
    If matches, return the result type. Need to return result type because we have parametric ploymorphism.
    """

    some_tp_mapping_candidates: Dict[int, List[e.Tp]] = {}

    args_ck_tps = tps_ck.args_tp
    ret_tp = tps_ck.ret_tp.tp

    if len(args_ck_tps) != len(tps_syn):
        return None
    
    for i, (syn_tp, ck_tp) in enumerate(zip(tps_syn, args_ck_tps)):
        tops.collect_is_subtype_with_instantiation(ctx, syn_tp, ck_tp, some_tp_mapping_candidates)

    some_tp_mapping: Dict[int, e.Tp] = {}
    for i, candidate_tps in some_tp_mapping_candidates.items():
        if len(candidate_tps) == 1:
            some_tp_mapping[i] = candidate_tps[0]
            continue
        else:
            for candidate_tp in candidate_tps:
                if all(tops.check_is_subtype(ctx, tp, candidate_tp) for tp in candidate_tps):
                    some_tp_mapping[i] = candidate_tp
                    break
            else:
                # the refined is used with the test case test_edgeql_select_subqueries_16
                # where for std::IN, one argument has a link prop and the other do not
                # I choose to remove the link prop uniformly in this case
                refined_candidate_tps = [refine_candidate_tp(tp) for tp in candidate_tps]
                for candidate_tp in refined_candidate_tps:
                    if all(tops.check_is_subtype(ctx, tp, candidate_tp) for tp in refined_candidate_tps):
                        some_tp_mapping[i] = candidate_tp
                        break
                else:
                    # cannot find a unique assignment for a candidate type
                    return None
        
    for i, (syn_tp, ck_tp) in enumerate(zip(tps_syn, args_ck_tps)):
        if tops.check_is_subtype_with_instantiation(ctx, syn_tp, ck_tp, some_tp_mapping):
            continue
        else:
            syn_tp = refine_candidate_tp(syn_tp) # use refinement if it fails on the first run
            if tops.check_is_subtype_with_instantiation(ctx, syn_tp, ck_tp, some_tp_mapping):
                continue
            else:
                return None

    final_ret_tp = tops.recursive_instantiate_tp(ret_tp, some_tp_mapping)
    return final_ret_tp
    # if isinstance(ret_tp, e.SomeTp):
    #     if ret_tp.index in some_tp_mapping:
    #         return some_tp_mapping[ret_tp.index]
    #     else:
    #         raise ValueError("Function's return type has to be grounded by input types.")
    # else:
    #     return ret_tp


def func_call_checking(ctx: e.TcCtx, fun_call: e.FunAppExpr) -> Tuple[e.ResultTp, e.FunAppExpr]:
    # for breaking circular dependency
    from . import typechecking as tc

    match fun_call:
        case e.FunAppExpr(fun=fname, args=args, overloading_index=idx, kwargs=kwargs):
            qualified_fname, fun_defs = mops.resolve_raw_name_and_func_def(ctx, fname)
            # assert len(args) == len(fun_tp.args_mod), "argument count mismatch"
            if args:
                [res_tps, args_cks] = zip(*[tc.synthesize_type(ctx, v) for v in args])
                [tps, arg_cards] = zip(*res_tps)
            else:
                tps = []
                arg_cards = []
                args_cks = []
            
            kwargs_ck = {k : tc.synthesize_type(ctx, v) for k, v in kwargs.items()}



            if idx is not None:
                args_ret_type = fun_defs[idx].tp
                assert len(kwargs) == 0, "idx must be concurrent with kwargs"
                result_tp = check_args_ret_type_match(ctx, tps, args_ret_type)
                if result_tp is None:
                    raise ValueError("Overloading for function incorrectly calculated", fun_call)
            else:
                ok_candidates : List[Tuple[int, e.Tp]] = []
                for i, fun_def in enumerate(fun_defs):
                    if len(tps) == len(fun_def.tp.args_tp):
                        if len(kwargs) == 0:
                            result_tp = check_args_ret_type_match(ctx, tps, fun_def.tp)
                        else:
                            pass
                    elif len(tps) > len(fun_def.tp.args_tp):
                        pass
                    elif len(tps) < len(fun_def.tp.args_tp):
                        new_tps = [*tps]
                        for i in range(len(tps), len(fun_def.tp.args_tp)):
                            label_i = fun_def.tp.args_label[i]
                            if label_i in kwargs:
                                new_tps = [*new_tps, kwargs_ck[label_i][0][0]]
                            elif label_i in fun_def.defaults:
                                default_expr = fun_def.defaults[label_i]
                                if default_expr == e.MultiSetExpr([]):
                                    new_tps = [*new_tps, fun_def.tp.args_tp[i]]
                                else:
                                    new_tps = [*new_tps, tc.synthesize_type(ctx, fun_def.defaults[label_i])[0][0]]
                            else:
                                result_tp = None
                                break
                        else:
                            result_tp = check_args_ret_type_match(ctx, new_tps, fun_def.tp)
                    if result_tp is not None:
                        ok_candidates.append((i, result_tp))
                
                if len(ok_candidates) > 1 :
                    print_warning("WARNING: Ambiguous overloading", pp.show_qname(qualified_fname),
                          "picking the first one")
                    ok_candidates = ok_candidates[0:1]

                if len(ok_candidates) == 0:
                    for i, fun_def in enumerate(fun_defs):
                        result_tp = check_args_ret_type_match(ctx, tps, fun_def.tp)
                    raise ValueError("No overloading matches", pp.show_qname(qualified_fname), 
                                     "args type", [pp.show_tp(tp) for tp in tps],
                                     "candidates", [pp.show_func_tps(fun_def.tp) for fun_def in fun_defs],
                                     pp.show_expr(fun_call))
                elif len(ok_candidates) == 1:
                    idx, result_tp = ok_candidates[0]
                else:
                    raise ValueError("Ambiguous overloading", pp.show_qname(qualified_fname), 
                                     "args type", [pp.show_tp(tp) for tp in tps],
                                     "candidates", [pp.show_func_tps(fun_def.tp) for fun_def in fun_defs],
                                     pp.show_expr(fun_call))

            if len(arg_cards) < len(fun_defs[idx].tp.args_mod):
                for i in range(len(tps), len(fun_def.tp.args_tp)):
                    label_i = fun_def.tp.args_label[i]
                    if label_i in kwargs:
                        arg_cards.append(kwargs_ck[label_i][0][1])
                    elif label_i in fun_def.defaults:
                        arg_cards.append(tc.synthesize_type(ctx, fun_def.defaults[label_i])[0][1])
                    else:
                        raise ValueError("impossible", fun_call)


            # take the product of argument cardinalities
            arg_card_product = reduce(
                operator.mul,
                (tops.match_param_modifier(param_mod, arg_card)
                    for param_mod, arg_card
                    in zip(fun_defs[idx].tp.args_mod, arg_cards, strict=True)), e.CardOne)
            result_card = (arg_card_product
                            * fun_defs[idx].tp.ret_tp.mode)
            # special processing of cardinality inference for certain functions
            match qualified_fname:
                case e.QualifiedName(["std", "??"]):
                    assert len(arg_cards) == 2
                    result_card = e.CMMode(
                        e.max_cardinal(arg_cards[0].lower,
                                        arg_cards[1].lower),
                        e.max_cardinal(arg_cards[0].upper,
                                        arg_cards[1].upper),
                    )
                case e.QualifiedName(["std", "assert_exists"]):
                    if result_card.lower == e.ZeroCardinal():
                        result_card = e.CMMode(e.OneCardinal(), arg_cards[0].upper)
                        # TODO preserve cardinality annotation
                case _:
                    pass

            if len(args_cks) < len(fun_defs[idx].tp.args_mod):
                for i in range(len(args_cks), len(fun_defs[idx].tp.args_tp)):
                    label_i = fun_defs[idx].tp.args_label[i]
                    if label_i in kwargs:
                        args_cks.append(kwargs_ck[label_i][1])
                    elif label_i in fun_defs[idx].defaults:
                        args_cks.append(tc.synthesize_type(ctx, fun_defs[idx].defaults[label_i])[1])
                    else:
                        raise ValueError("impossible", fun_call)

            result_expr = e.FunAppExpr(fun=qualified_fname, args=args_cks, overloading_index=idx, kwargs={})
            return (e.ResultTp(result_tp, result_card), result_expr)
        case _:
            raise ValueError("impossible", fun_call)
            
    
    # result_tp = args_ret_type.ret_tp.tp
    #         result_expr = e.FunAppExpr(fun=fname, args=arg_cks,
    #                                     overloading_index=idx)
    #         return result_tp, result_card, result_expr

