import os
import tempfile
from app.models.schemas import MovimientoBancario
from datetime import datetime

from app.services.bancos import BcoBBVA, BcoGAL, BcoICBC, BcoRIO, BcoPBA
from app.services.bancos import BcoSUPV, BcoCMF, BcoHIPO, BcoBBK, BcoMP

def _log(msg):
    try:
        print(str(msg))
    except Exception:
        pass

def _df_to_movimientos(df):
    movimientos = []
    try:
        for _, row in df.iterrows():
            try:
                fecha = row.get('FECHA') or row.get('Fecha') or row.get('fecha')
                if hasattr(fecha, 'date'):
                    f = fecha.date()
                elif isinstance(fecha, str):
                    f = None
                    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                        try:
                            f = datetime.strptime(fecha.strip(), fmt).date()
                            break
                        except Exception:
                            pass
                    if f is None:
                        f = datetime.now().date()
                else:
                    f = datetime.now().date()
                concepto = str(row.get('DETALLE') or row.get('Concepto') or row.get('concepto') or '').strip()
                debe = float(row.get('DEBE') or row.get('Debe') or 0.0)
                haber = float(row.get('HABER') or row.get('Haber') or 0.0)
                saldo = float(row.get('SALDO') or row.get('Saldo') or row.get('SALDO_CALC') or 0.0)
                movimientos.append(MovimientoBancario(fecha=f, concepto=concepto, debe=debe, haber=haber, saldo=saldo))
            except Exception:
                continue
    except Exception:
        pass
    return movimientos

def procesar_archivo(banco_id: str, ruta_pdf: str) -> list[MovimientoBancario]:
    banco = banco_id.upper().strip()
    movimientos = []
    try:
        if banco not in ('BBVA','GAL','ICBC','RIO','PBA','SUPV','CMF','HIPO','BBK','MP'):
            raise ValueError(f"El formato del banco '{banco}' no está soportado.")
        fd, excel_tmp = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        try:
            try:
                if banco == 'BBVA':
                    res = BcoBBVA.extraer_bbva(ruta_pdf, excel_tmp, _log)
                elif banco == 'GAL':
                    res = BcoGAL.extraer_galicia(ruta_pdf, excel_tmp, _log)
                elif banco == 'ICBC':
                    res = BcoICBC.extraer_icbc(ruta_pdf, excel_tmp, _log)
                elif banco == 'RIO':
                    res = BcoRIO.extraer_santander(ruta_pdf, excel_tmp, _log)
                elif banco == 'PBA':
                    res = BcoPBA.extraer_provincia(ruta_pdf, excel_tmp, _log)
                elif banco == 'SUPV':
                    res = BcoSUPV.extraer_supervielle(ruta_pdf, excel_tmp, _log)
                elif banco == 'CMF':
                    res = BcoCMF.extraer_cmf(ruta_pdf, excel_tmp, _log)
                elif banco == 'HIPO':
                    res = BcoHIPO.extraer_hipotecario(ruta_pdf, excel_tmp, _log)
                elif banco == 'BBK':
                    res = BcoBBK.extraer_brubank(ruta_pdf, excel_tmp, _log)
                elif banco == 'MP':
                    res = BcoMP.extraer_mp(ruta_pdf, excel_tmp, _log)
            except Exception as e:
                # No relanzar - devolver movimientos vacíos para no romper conexión frontend
                return []
            try:
                if os.path.exists(excel_tmp):
                    import pandas as pd
                    df = pd.read_excel(excel_tmp)
                    movimientos = _df_to_movimientos(df)
            except Exception:
                movimientos = []
        finally:
            if os.path.exists(excel_tmp):
                try:
                    os.remove(excel_tmp)
                except Exception:
                    pass
        return movimientos
    finally:
        if os.path.exists(ruta_pdf):
            try:
                os.remove(ruta_pdf)
            except Exception:
                pass
