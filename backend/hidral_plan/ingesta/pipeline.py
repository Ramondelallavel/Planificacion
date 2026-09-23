"""Pipeline de ingestión documental.

    PDF → hash/duplicados/versiones → (cola) → tamaño de bloque → por cada bloque:
        extracción de texto (OCR solo si no hay texto) → clasificación → parser con contexto
        ligero → persistencia del bloque + punto de control → liberar memoria
    → post-proceso: grafo de OF, ciclos, semanas, operaciones/tiempos, validación, resumen.

El trabajo es reanudable: cada bloque se guarda junto con el contexto documental en la
misma transacción; si el proceso cae, se retoma desde el último bloque completado.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf
from sqlalchemy import select

from ..config import ajustes
from ..db import sesion
from ..modelos import Documento, OrdenFabricacion, Tanda, TrabajoProcesamiento
from ..modelos.comun import ahora
from ..modelos.enums import EstadoDocumento, EstadoTrabajo, Severidad, TipoPagina
from ..servicios.auditoria import auditar
from ..servicios.operaciones import derivar_operaciones
from .almacen import AlmacenLocal, hash_fichero
from .bloques import ajustar_tamano, estimar_tamano_bloque
from .clasificador import clasificar
from .contexto import ContextoDocumento
from .extraccion import extraer_pagina
from .grafo import asegurar_secciones, construir_dependencias, detectar_ciclos, enlazar_aparatos
from .parsers import parsear_pagina
from .persistencia import EstadoPersistencia, persistir_bloque, resolver_pendientes
from .registros import RegAparato, RegAviso, RegBulto, RegComponenteBulto, RegOF
from .validacion import completar_semanas, resumen_documento, validar

log = logging.getLogger(__name__)

TIPOS_HOJA = {TipoPagina.HOJA_GRUPO_HF, TipoPagina.HOJA_CAB_PUERTAS, TipoPagina.HOJA_LCH}


@dataclass
class ResultadoCarga:
    documento_id: int
    trabajo_id: int | None
    duplicado: bool
    nueva_version: bool
    version: int
    mensaje: str


def _clave_logica(doc: pymupdf.Document) -> str | None:
    import re

    for i in range(min(3, doc.page_count)):
        pg = doc.load_page(i)
        m = re.search(r"TANDA\s+(\d+)", pg.get_text("text"))
        del pg
        if m:
            return f"TANDA {m.group(1)}"
    return None


def registrar_documento(temporal: Path, nombre: str, usuario: str) -> ResultadoCarga:
    """Guarda el fichero, detecta duplicados por hash y versiones por clave lógica, y encola el trabajo.
    Devuelve inmediatamente: el procesamiento ocurre en segundo plano."""
    h, tam = hash_fichero(temporal)
    with sesion() as s:
        existente = s.scalar(select(Documento).where(Documento.hash_sha256 == h))
        if existente is not None:
            temporal.unlink(missing_ok=True)
            auditar(
                s,
                usuario,
                "IMPORTACION_DUPLICADA",
                "DOCUMENTO",
                existente.id,
                despues={"nombre": nombre, "hash": h},
                motivo="Mismo hash que un documento ya cargado: no se reprocesa",
            )
            trabajo = s.scalar(select(TrabajoProcesamiento).where(TrabajoProcesamiento.documento_id == existente.id).order_by(TrabajoProcesamiento.id.desc()))
            return ResultadoCarga(
                existente.id,
                trabajo.id if trabajo else None,
                True,
                False,
                existente.version,
                f"Documento idéntico ya cargado el {existente.fecha_carga:%d/%m/%Y %H:%M} por {existente.usuario_carga} (versión {existente.version}). No se reprocesa.",
            )
        ruta = AlmacenLocal().guardar_desde_temporal(temporal, h)
        try:
            with pymupdf.open(ruta) as doc:
                n = doc.page_count
                clave = _clave_logica(doc)
        except Exception as exc:
            d = Documento(
                nombre=nombre,
                hash_sha256=h,
                tamano_bytes=tam,
                usuario_carga=usuario,
                estado=EstadoDocumento.ERROR,
                ruta_almacen=str(ruta),
                resumen={"error": f"PDF ilegible: {exc}"},
            )
            s.add(d)
            s.flush()
            auditar(s, usuario, "IMPORTACION_ERROR", "DOCUMENTO", d.id, despues={"error": str(exc)})
            return ResultadoCarga(d.id, None, False, False, 1, f"El fichero no es un PDF legible: {exc}")
        anterior = None
        if clave:
            anterior = s.scalar(select(Documento).where(Documento.clave_logica == clave, Documento.estado != EstadoDocumento.ERROR).order_by(Documento.version.desc()))
        d = Documento(
            nombre=nombre,
            hash_sha256=h,
            tamano_bytes=tam,
            num_paginas=n,
            usuario_carga=usuario,
            estado=EstadoDocumento.EN_COLA,
            clave_logica=clave,
            version=(anterior.version + 1) if anterior else 1,
            documento_anterior_id=anterior.id if anterior else None,
            ruta_almacen=str(ruta),
        )
        s.add(d)
        s.flush()
        t = TrabajoProcesamiento(documento_id=d.id, paginas_totales=n, estado=EstadoTrabajo.EN_COLA, fase="En cola", contadores={})
        s.add(t)
        s.flush()
        auditar(s, usuario, "IMPORTACION_CARGA", "DOCUMENTO", d.id, despues={"nombre": nombre, "hash": h, "paginas": n, "clave": clave, "version": d.version})
        msg = f"{n} páginas en cola de procesamiento"
        if anterior:
            msg = f"Nueva versión {d.version} de {clave} (anterior: documento {anterior.id}). " + msg
        return ResultadoCarga(d.id, t.id, False, anterior is not None, d.version, msg)


def _pendientes_a_json(est: EstadoPersistencia) -> list:
    return (
        [["RegAparato", asdict(r)] for r in est.aparatos_pendientes]
        + [["RegBulto", asdict(r)] for r in est.bultos_pendientes]
        + [["RegComponenteBulto", asdict(r)] for r in est.componentes_pendientes]
    )


def _pendientes_desde_json(est: EstadoPersistencia, datos: list | None) -> None:
    clases = {"RegAparato": RegAparato, "RegBulto": RegBulto, "RegComponenteBulto": RegComponenteBulto}
    for nombre, d in datos or []:
        r = clases[nombre](**d)
        {"RegAparato": est.aparatos_pendientes, "RegBulto": est.bultos_pendientes, "RegComponenteBulto": est.componentes_pendientes}[nombre].append(r)


def procesar_trabajo(trabajo_id: int, trabajador: str = "local") -> None:
    cfg = ajustes()
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, trabajo_id)
        if t is None:
            return
        d = s.get(Documento, t.documento_id)
        assert d is not None
        t.estado = EstadoTrabajo.PROCESANDO
        t.trabajador = trabajador
        t.inicio = t.inicio or ahora()
        t.latido = ahora()
        t.fase = "Extrayendo"
        d.estado = EstadoDocumento.PROCESANDO
        ruta, tam_bytes, documento_id = d.ruta_almacen, d.tamano_bytes, d.id
        contadores = dict(t.contadores or {})
        pagina, bloque, tam = t.paginas_procesadas, t.bloque_actual, t.tamano_bloque
    try:
        _procesar(trabajo_id, documento_id, Path(ruta), tam_bytes, contadores, pagina, bloque, tam, cfg)
    except Exception as exc:
        log.exception("Fallo procesando documento %s", documento_id)
        with sesion() as s:
            t = s.get(TrabajoProcesamiento, trabajo_id)
            d = s.get(Documento, documento_id)
            if t:
                t.estado = EstadoTrabajo.ERROR
                t.mensaje_error = f"{type(exc).__name__}: {exc}"
                t.fin = ahora()
            if d:
                d.estado = EstadoDocumento.ERROR
            auditar(s, "sistema", "IMPORTACION_ERROR", "DOCUMENTO", documento_id, despues={"error": str(exc)}, automatica=True)


def _procesar(trabajo_id: int, documento_id: int, ruta: Path, tam_bytes: int, contadores: dict, pagina: int, bloque: int, tam: int, cfg) -> None:
    ctx = ContextoDocumento.desde_dict(contadores.get("contexto"))
    est = EstadoPersistencia(documento_id=documento_id)
    est.ofs_reiniciadas = set(ctx.ofs_vistas)
    _pendientes_desde_json(est, contadores.get("pendientes"))
    aparatos_vistos: set[str] = set(contadores.get("aparatos_lista", []))
    secciones_vistas: set[str] = set(contadores.get("secciones_lista", []))
    if ctx.tanda_numero:
        with sesion() as s:
            est.tanda_id = s.scalar(select(Tanda.id).where(Tanda.numero == ctx.tanda_numero))
            if est.tanda_id:
                est.tandas[ctx.tanda_numero] = est.tanda_id

    t_inicio = time.monotonic()
    paginas_inicio = pagina
    with pymupdf.open(ruta) as doc:
        n = doc.page_count
        if not tam:
            plan = estimar_tamano_bloque(doc, tam_bytes, cfg.bloque_min_paginas, cfg.bloque_max_paginas, cfg.bloque_memoria_mb)
            tam = plan.tamano_inicial
            contadores["plan_bloques"] = plan.motivo
        while pagina < n:
            with sesion() as s:
                t = s.get(TrabajoProcesamiento, trabajo_id)
                if t is None or t.estado == EstadoTrabajo.CANCELADO:
                    return
            fin = min(n, pagina + tam)
            t_bloque = time.monotonic()
            registros: list = []
            paginas_meta: list[dict] = []
            for i in range(pagina, fin):
                pe = extraer_pagina(doc, i, cfg.ocr)
                cl = clasificar(pe)
                regs = parsear_pagina(cl.tipo, pe, ctx)
                registros.extend(regs)
                ofs_pag = [r.numero for r in regs if isinstance(r, RegOF)]
                avisos = [r for r in regs if isinstance(r, RegAviso)]
                for r in regs:
                    if isinstance(r, RegAparato):
                        aparatos_vistos.add(r.numero_control)
                if cl.tipo in TIPOS_HOJA and ctx.seccion_codigo:
                    secciones_vistas.add(ctx.seccion_codigo)
                contadores["ofs"] = contadores.get("ofs", 0) + len(ofs_pag)
                contadores["advertencias"] = contadores.get("advertencias", 0) + sum(1 for a in avisos if a.severidad == Severidad.ADVERTENCIA)
                contadores["errores"] = contadores.get("errores", 0) + sum(1 for a in avisos if a.severidad == Severidad.ERROR)
                contadores["criticos"] = contadores.get("criticos", 0) + sum(1 for a in avisos if a.severidad == Severidad.CRITICA)
                contadores.setdefault("tipos_pagina", {})
                contadores["tipos_pagina"][cl.tipo.value] = contadores["tipos_pagina"].get(cl.tipo.value, 0) + 1
                paginas_meta.append(
                    {
                        "numero": pe.numero,
                        "tipo": cl.tipo.value,
                        "metodo_extraccion": pe.metodo,
                        "num_caracteres": pe.num_caracteres,
                        "seccion_codigo": ctx.seccion_codigo if cl.tipo in TIPOS_HOJA else None,
                        "grupo_hf": ctx.grupo_hf if cl.tipo in TIPOS_HOJA else None,
                        "pagina_de": f"{ctx.pagina_de[0]} de {ctx.pagina_de[1]}" if (cl.tipo in TIPOS_HOJA and ctx.pagina_de) else None,
                        "ofs_detectadas": ofs_pag or None,
                        "avisos": len(avisos),
                        "texto": pe.texto,
                    }
                )
                del pe
            contadores["aparatos"] = len(aparatos_vistos)
            contadores["aparatos_lista"] = sorted(aparatos_vistos)
            contadores["secciones"] = len(secciones_vistas)
            contadores["secciones_lista"] = sorted(secciones_vistas)
            with sesion() as s:
                persistir_bloque(s, est, registros, paginas_meta, bloque)
                contadores["contexto"] = ctx.a_dict()
                contadores["pendientes"] = _pendientes_a_json(est)
                t = s.get(TrabajoProcesamiento, trabajo_id)
                assert t is not None
                t.paginas_procesadas = fin
                t.bloque_actual = bloque + 1
                t.tamano_bloque = tam
                t.bloques_totales = bloque + 1 + -(-(n - fin) // tam)
                t.latido = ahora()
                transcurrido = time.monotonic() - t_inicio
                hechas = fin - paginas_inicio
                t.eta_segundos = int(transcurrido / hechas * (n - fin)) if hechas else None
                t.fase = f"Bloque {bloque + 1}: páginas {pagina + 1}-{fin} de {n}"
                t.contadores = dict(contadores)
            registros.clear()
            paginas_meta.clear()
            pymupdf.TOOLS.store_shrink(100)  # vacía la caché interna de MuPDF entre bloques
            tam = ajustar_tamano(tam, time.monotonic() - t_bloque, fin - pagina, cfg.bloque_min_paginas, cfg.bloque_max_paginas)
            pagina = fin
            bloque += 1

    _postproceso(trabajo_id, documento_id, est, contadores)


def _postproceso(trabajo_id: int, documento_id: int, est: EstadoPersistencia, contadores: dict) -> None:
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, trabajo_id)
        assert t is not None
        t.fase = "Validando y construyendo el grafo de fabricación"
    with sesion() as s:
        resolver_pendientes(s, est)
        s.flush()
        d = s.get(Documento, documento_id)
        assert d is not None
        tanda_id = est.tanda_id
        asegurar_secciones(s, documento_id)
        of_ids = list(s.scalars(select(OrdenFabricacion.id).where(OrdenFabricacion.documento_id == documento_id)))
        enlazar_aparatos(s, documento_id, of_ids)
        s.flush()
        grafo = construir_dependencias(s, documento_id, tanda_id)
        ciclos = detectar_ciclos(s, documento_id, set(s.scalars(select(OrdenFabricacion.id).where(OrdenFabricacion.tanda_id == tanda_id))) if tanda_id else None)
        if tanda_id:
            completar_semanas(s, documento_id, tanda_id)
        of_ids = list(s.scalars(select(OrdenFabricacion.id).where(OrdenFabricacion.documento_id == documento_id)))
        ops = derivar_operaciones(s, of_ids, documento_id)
        validar(s, documento_id, tanda_id)
        s.flush()
        cambios_version = None
        if d.documento_anterior_id:
            ausentes = list(s.scalars(select(OrdenFabricacion.numero).where(OrdenFabricacion.documento_id == d.documento_anterior_id, OrdenFabricacion.tiene_hoja.is_(True))))
            anterior = s.get(Documento, d.documento_anterior_id)
            if anterior:
                anterior.estado = EstadoDocumento.SUSTITUIDO
            if ausentes:
                from ..modelos import IncidenciaDatos

                s.add(
                    IncidenciaDatos(
                        documento_id=documento_id,
                        tipo="OF_AUSENTE_EN_NUEVA_VERSION",
                        severidad=Severidad.ADVERTENCIA,
                        mensaje=f"{len(ausentes)} OF de la versión anterior no aparecen en esta versión. No se han eliminado: REVISIÓN NECESARIA.",
                        entidad_tipo="DOCUMENTO",
                        entidad_ref=str(documento_id),
                        alternativas=ausentes[:200],
                    )
                )
            cambios_version = {
                "ofs_nuevas": est.contadores.get("ofs", 0),
                "ofs_actualizadas": len(est.ofs_reiniciadas) - est.contadores.get("ofs", 0),
                "ofs_ausentes": ausentes,
            }
        resumen = resumen_documento(s, documento_id, tanda_id)
        resumen.update(
            paginas=d.num_paginas,
            dependencias=grafo["dependencias"],
            ciclos=len(ciclos),
            operaciones=ops.get("operaciones", 0),
            operaciones_sin_tiempo=ops.get("sin_tiempo", 0),
            operaciones_sin_recurso=ops.get("sin_recurso", 0),
            tipos_pagina=contadores.get("tipos_pagina", {}),
            plan_bloques=contadores.get("plan_bloques"),
            bloques=t.bloque_actual if (t := s.get(TrabajoProcesamiento, trabajo_id)) else None,
            cambios_version=cambios_version,
            tanda=s.get(Tanda, tanda_id).numero if tanda_id else None,
        )
        d.resumen = resumen
        d.fecha_fin = ahora()
        d.estado = EstadoDocumento.COMPLETADO_CON_ERRORES if (resumen["criticas"] or resumen["errores"]) else EstadoDocumento.COMPLETADO
        if t:
            t.estado = EstadoTrabajo.COMPLETADO
            t.fin = ahora()
            t.fase = "Completado"
            t.eta_segundos = 0
            c = dict(t.contadores or {})
            c.pop("pendientes", None)
            c.pop("contexto", None)  # el contexto ya no es necesario una vez terminado
            t.contadores = c
        auditar(
            s,
            d.usuario_carga,
            "IMPORTACION_COMPLETADA",
            "DOCUMENTO",
            documento_id,
            despues={k: v for k, v in resumen.items() if k != "por_tipo"},
            automatica=True,
        )


def procesar_sincrono(temporal: Path, nombre: str, usuario: str = "sistema") -> ResultadoCarga:
    """Carga y procesa en el mismo hilo (CLI y tests)."""
    r = registrar_documento(temporal, nombre, usuario)
    if r.trabajo_id and not r.duplicado:
        procesar_trabajo(r.trabajo_id)
    return r
