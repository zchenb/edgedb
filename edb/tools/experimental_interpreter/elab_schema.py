
from typing import Any, Dict, Optional, Sequence, Tuple, Union, cast

from edb.edgeql import ast as qlast

from .basis.built_ins import all_builtin_funcs
from .data.data_ops import (CMMode, DBSchema, LinkPropTp, ObjectTp,
                            ResultTp, Tp)
from .elaboration import elab_single_type_expr, elab_expr_with_default_head
from .helper_funcs import parse_sdl
from .data import data_ops as e
from . import typechecking  as tck

def elab_schema_error(obj: Any) -> Any:
    raise ValueError(obj)


def elab_schema_cardinality(
        is_required: Optional[bool],
        cardinality: Optional[qlast.qltypes.SchemaCardinality]) -> CMMode:
    return CMMode(e.CardNumOne if is_required else e.CardNumZero,
                  e.CardNumInf
                  if cardinality == qlast.qltypes.SchemaCardinality.Many
                  else e.CardNumOne)


def elab_schema_target_tp(
        target: Optional[Union[qlast.Expr, qlast.TypeExpr]]) -> Tp:
    return (elab_single_type_expr(target)
            if isinstance(target, qlast.TypeExpr)
            else elab_schema_error(target))


def elab_schema(sdef: qlast.Schema) -> DBSchema:
    if (len(sdef.declarations) != 1
            or sdef.declarations[0].name.name != "default"):
        raise ValueError(
            "Expect single module declaration named default in schema")
    types_decls = cast(
        Sequence[qlast.ModuleDeclaration],
        sdef.declarations)[0].declarations

    type_defs: Dict[str, ObjectTp] = {}
    for t_decl in types_decls:
        match t_decl:
            case qlast.CreateObjectType(bases=_,
                                        commands=commands,
                                        name=qlast.ObjectRef(name=name),
                                        abstract=_):
                object_tp_content: Dict[str, ResultTp] = {}
                for cmd in commands:
                    match cmd:
                        case qlast.CreateConcretePointer(
                                bases=_,
                                name=qlast.ObjectRef(name=pname),
                                target=ptarget,
                                is_required=p_is_required,
                                cardinality=p_cardinality,
                                commands=pcommands):
                            if isinstance(ptarget, qlast.TypeExpr):
                                base_target_type = elab_schema_target_tp(
                                    ptarget)
                            elif isinstance(ptarget, qlast.Expr):
                                base_target_type = e.UncheckedComputableTp(
                                    elab_expr_with_default_head(ptarget)
                                )
                            else:
                                print(
                                    "WARNING: not implemented ptarget",
                                    ptarget)
                            link_property_tps: Dict[str, ResultTp] = {}
                            p_has_set_default: Optional[e.BindingExpr] = None
                            for pcmd in pcommands:
                                match pcmd:
                                    case qlast.CreateConcretePointer(
                                            bases=_,
                                            name=qlast.ObjectRef(name=plname),
                                            target=pltarget,
                                            is_required=pl_is_required,
                                            cardinality=pl_cardinality,
                                            commands=plcommands):
                                        pl_has_set_default: Optional[
                                            e.BindingExpr] = None
                                        if plcommands:
                                            for plcommand in plcommands:
                                                match plcommand:
                                                    case qlast.SetField(
                                                            name=set_field_name,  # noqa: E501
                                                            value=set_field_value):  # noqa: E501
                                                        match set_field_name:
                                                            case "default":
                                                                assert isinstance(set_field_value, qlast.Expr)  # noqa: E501
                                                                pl_has_set_default = (  # noqa: E501
                                                                    elab_expr_with_default_head(  # noqa: E501
                                                                            set_field_value))  # noqa: E501
                                                            case _:
                                                                print(
                                                                    "WARNING: "
                                                                    "not "
                                                                    "implemented "  # noqa: E501
                                                                    "set_field_name",  # noqa: E501
                                                                    set_field_name)  # noqa: E501
                                                    case _:
                                                        print(
                                                            "WARNING: not "
                                                            "implemented plcmd",  # noqa: E501
                                                            plcommand)
                                        if isinstance(
                                                pltarget, qlast.TypeExpr):
                                            lp_base_tp = elab_schema_target_tp(
                                                    pltarget)
                                        elif isinstance(pltarget, qlast.Expr):
                                            lp_base_tp = (
                                             e.UncheckedComputableTp(
                                              elab_expr_with_default_head(
                                                    pltarget))
                                            )
                                        else:
                                            print(
                                                "WARNING: "
                                                "not implemented pltarget",
                                                pltarget)
                                        if pl_has_set_default is not None:
                                            assert not isinstance(
                                                lp_base_tp,
                                                e.UncheckedComputableTp)
                                            assert not isinstance(
                                                lp_base_tp,
                                                e.ComputableTp)
                                            lp_base_tp = e.DefaultTp(
                                                pl_has_set_default,
                                                lp_base_tp)
                                        link_property_tps = {
                                            **link_property_tps,
                                            plname:
                                            ResultTp(
                                                lp_base_tp,
                                                elab_schema_cardinality(
                                                        pl_is_required,
                                                        pl_cardinality
                                                        ))}
                                    case qlast.CreateConcreteConstraint():
                                        print("WARNING: not implemented pcmd"
                                              " (constraint)", pcmd)
                                    case qlast.SetField(
                                            name=set_field_name,
                                            value=set_field_value):
                                        match set_field_name:
                                            case "default":
                                                assert isinstance(set_field_value, qlast.Expr)  # noqa: E501
                                                p_has_set_default = (
                                                 elab_expr_with_default_head(
                                                        set_field_value))
                                            case _:
                                                print(
                                                    "WARNING: "
                                                    "not implemented "
                                                    "set_field_name",
                                                    set_field_name)
                                    case _:
                                        print(
                                            "WARNING: not "
                                            "implemented pcmd",
                                            pcmd)
                            final_target_type = (
                                LinkPropTp(base_target_type,
                                           ObjectTp(link_property_tps))
                                if link_property_tps
                                else base_target_type)
                            if p_has_set_default is not None:
                                assert not isinstance(final_target_type,
                                                      e.UncheckedComputableTp)
                                assert not isinstance(final_target_type,
                                                      e.ComputableTp)
                                final_target_type = (
                                    e.DefaultTp(expr=p_has_set_default,
                                                tp=final_target_type))
                            object_tp_content = {
                                **object_tp_content,
                                pname:
                                ResultTp(final_target_type,
                                         elab_schema_cardinality(
                                          is_required=p_is_required,
                                          cardinality=p_cardinality))}
                        case _:
                            print("WARNING: not implemented cmd", cmd)
                            # debug.dump(cmd)

                type_defs = {**type_defs,
                             name: ObjectTp(val=object_tp_content)}
            case _:
                print("WARNING: not implemented t_decl", t_decl)

    return DBSchema(type_defs, all_builtin_funcs)


def schema_from_sdl_defs(schema_defs: str,
                         ) -> DBSchema:
    raw_schema = elab_schema(parse_sdl(schema_defs))
    checked_schema = tck.check_schmea_validity(raw_schema)
    return checked_schema



def schema_from_sdl_file(init_sdl_file_path: str,
                         ) -> DBSchema:
    with open(init_sdl_file_path) as f:
        return schema_from_sdl_defs(f.read())
