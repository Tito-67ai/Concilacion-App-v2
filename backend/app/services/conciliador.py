import pandas as pd
from app.models.schemas import MovimientoBancario

def conciliar_movimientos(movimientos_banco: list[MovimientoBancario], movimientos_xubio: list[dict]) -> dict:
    # 1. Convertir Pydantic y Diccionarios a DataFrames de Pandas
    df_banco = pd.DataFrame([m.model_dump() for m in movimientos_banco])
    df_xubio = pd.DataFrame(movimientos_xubio)
    
    if df_banco.empty or df_xubio.empty:
        return {"conciliados": [], "pendientes_banco": [], "pendientes_xubio": []}

    # 2. Crear una llave de cruce matemática (Debe - Haber)
    # En el banco, un ingreso es Haber. En Xubio, un ingreso es Debe. 
    # Invertimos el signo de uno para buscar la coincidencia exacta.
    df_banco['llave_monto'] = df_banco['haber'] - df_banco['debe']
    df_xubio['llave_monto'] = df_xubio['debe'] - df_xubio['haber']

    # 3. Ejecutar el cruce (Outer Join) indicando de dónde viene cada fila
    df_cruce = pd.merge(
        df_banco, 
        df_xubio, 
        on='llave_monto', 
        how='outer', 
        indicator=True,
        suffixes=('_bco', '_xub')
    )
    
    # 4. Separar las 3 bandejas de resultados y limpiar los NaN para Angular
    df_cruce = df_cruce.fillna("")
    
    conciliados = df_cruce[df_cruce['_merge'] == 'both'].to_dict('records')
    pend_banco = df_cruce[df_cruce['_merge'] == 'left_only'].to_dict('records')
    pend_xubio = df_cruce[df_cruce['_merge'] == 'right_only'].to_dict('records')
    
    return {
        "conciliados": conciliados,
        "pendientes_banco": pend_banco,
        "pendientes_xubio": pend_xubio
    }