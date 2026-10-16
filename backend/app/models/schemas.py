from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Literal, Optional
from datetime import date, datetime


def _normalizar_fecha(valor: Any) -> Any:
    """Acepta las dos formas de fecha que se manejan en el proyecto.

    El cruce devuelve 'fecha' como date en los pendientes y como string ISO en
    los pares (conciliador.py:171), y el extractor de tablas puede mandar
    dd/mm/yyyy. Si el schema solo aceptara ISO, un papel de trabajo con una
    fecha en formato argentino no se exportaria: el 422 seria del backend y no
    de la conciliacion, que es imposible de adivinar desde la pantalla.
    """
    if not isinstance(valor, str):
        return valor
    texto = valor.strip()
    if not texto:
        return None
    if texto[0].isdigit() and "/" in texto:
        try:
            return datetime.strptime(texto, "%d/%m/%Y").date()
        except ValueError:
            return valor
    return texto

class MovimientoBancario(BaseModel):
    fecha: date
    concepto: str
    referencia: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    saldo: float
    # 'operativo', 'percepcion' o 'impuesto'. Solo etiqueta: no cambia el importe
    # ni si la fila participa del cruce. Sirve para que la pantalla pueda
    # esconder las percepciones e impuestos, que no son operaciones de la
    # empresa y casi nunca encuentran su par en Xubio.
    #
    # None y no 'operativo' a proposito: la etiqueta se deriva del concepto, no
    # se afirma a mano. Con el default puesto, un MovimientoBancario armado a
    # mano quedaria marcado como operativo sin clasificar nunca, y el filtro lo
    # esconderia de la bandeja sin que nadie lo haya decidido.
    categoria: Optional[str] = None
    
class RespuestaExtraccion(BaseModel):
    exito: bool
    banco: str
    # De donde se leyeron los movimientos: 'pdf' o 'tabla'. Opcional para que el
    # frontend no rompa si habla con un backend que no lo manda.
    origen: Optional[str] = None
    # Que extractor leyo el archivo. Sirve para ver cuando el motor generico
    # entra de rescate porque el parser del banco no pudo con ese PDF.
    motor: Optional[str] = None
    cantidad_movimientos: int
    datos: list[MovimientoBancario]


# ----------------------------------------------------------------------
# Libro Mayor cargado desde archivo y cruce local
# ----------------------------------------------------------------------
#
# La API de Xubio esta reservada a planes superiores al contratado, asi que el
# mayor entra como archivo exportado desde el navegador (app/api/rutas/
# conciliacion.py). Estos schemas son la otra mitad de ese camino.


class MovimientoMayor(BaseModel):
    """Una fila del Libro Mayor: lo que le falta al extracto para poder cruzar."""

    fecha: Optional[date] = None
    concepto: str = ""
    # El numero de comprobante (FCA-0001-00000001, etc.) cuando el export del
    # contable trae la columna (COMPROBANTE/NROCOMPROBANTE). La bandeja derecha
    # lo muestra junto a la fecha y el detalle: sin el, la fila se ve con '—'.
    comprobante: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    # Campos adicionales que el importador ya lee (documento/cuenta/organizacion
    # del webreport y de algunos exports del contable) y que el papel de trabajo
    # escribe en las columnas B/C/H del Libro Mayor. Sin declararlos acá, FastAPI
    # los borraba de la respuesta de POST /conciliacion/mayor (response_model) y
    # el Excel salía con Documento y Cuenta vacíos aunque el archivo los trajera.
    documento: Optional[str] = None
    cuenta: Optional[str] = None
    organizacion: Optional[str] = None
    descripcion: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class RespuestaMayor(BaseModel):
    exito: bool
    cantidad_movimientos: int
    # 'contable' (Debe = entrada) si el archivo era un Libro Mayor, o 'cuenta'
    # (debito = salida) si era un extracto de Movimientos de CC de Xubio. La
    # pantalla lo muestra para que nadie confunda una convencion con la otra.
    convencion: str = "contable"
    datos: list[MovimientoMayor]


class SolicitudCruce(BaseModel):
    """Las dos bandejas de entrada para cruzar sin pasar por la API de Xubio."""

    movimientos_banco: list[MovimientoBancario]
    movimientos_xubio: list[MovimientoMayor] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Exportacion del papel de trabajo (FO 02-03)
# ----------------------------------------------------------------------
#
# Lo que se exporta es el ESTADO de la conciliacion tal como quedo en la
# pantalla, no un cruce nuevo. Por eso el frontend manda las tres bandejas que
# ya tiene en memoria: si el exportador volviera a cruzar contra Xubio, el
# papel de trabajo podria no coincidir con lo que el usuario acabo de revisar
# (por ejemplo si hay pares armados a mano, que el backend nunca vio).


class EncabezadoConciliacion(BaseModel):
    """Los cuatro campos del membrete de FO 02-03."""

    empresa: str = ""
    banco: str = ""
    numero_cuenta: str = ""
    # El periodo va como 'YYYY-MM' porque la celda I5 de la plantilla tiene
    # formato 'mmmm yyyy': hay que escribir una fecha de Excel, no un texto.
    # Vacio significa "no se informo".
    periodo: Optional[str] = None


class ParConciliado(BaseModel):
    """Una fila de la pestana "Movimientos conciliados".

    Los dos campos 'fecha' y 'importe' los manda el cruce con convenciones
    distintas (conciliador.py): el banco unifica como haber - debe, Xubio como
    debe - haber. Si el frontend no manda 'importe', el exportador lo recalcula
    desde debe/haber del banco para no dejar la celda en cero.
    """

    fecha: Optional[date] = None
    concepto_banco: str = ""
    concepto_xubio: str = ""
    debe: float = 0.0
    haber: float = 0.0
    saldo: float = 0.0
    importe: Optional[float] = None
    categoria: Optional[str] = None
    # Que lo emparejo una persona y no el cruce automatico. Los pares
    # automaticos no mandan estos dos campos.
    manual: bool = False
    diferencia: Optional[float] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class PendienteExport(BaseModel):
    """Una fila sin cruzar, de cualquiera de los dos lados.

    'origen' distingue la bandeja: los pendientes del banco traen saldo y
    categoria, los de Xubio no. 'comprobante' es el numero de documento del
    mayor (FCA-0001-00000001): la Tabla 2 del papel lo escribe en "Documento".
    """

    origen: str = "banco"
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    comprobante: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    saldo: float = 0.0
    importe: Optional[float] = None
    categoria: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class MovimientoMayorExport(BaseModel):
    """Una fila del Libro Mayor para la Tabla 1 del papel de trabajo.

    Campos del webreport de Xubio: fecha, concepto, comprobante, debe, haber,
    documento, cuenta, organizacion, descripcion.
    """

    fecha: Optional[date] = None
    concepto: str = ""
    comprobante: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    documento: Optional[str] = None
    cuenta: Optional[str] = None
    organizacion: Optional[str] = None
    descripcion: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class MovimientoBancoExport(BaseModel):
    """Una fila del extracto para la pestana "Movimientos Bancarios".

    La pestana "Movimientos Bancarios" muestra el extracto resumido en cinco
    columnas: fecha, concepto, debito, credito y saldo. El modelo conserva
    ademas referencia, que el exportador usa para deduplicar lineas repetidas.
    """

    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    saldo: float = 0.0

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class SolicitudExportacion(BaseModel):
    conciliados: list[ParConciliado] = Field(default_factory=list)
    pendientes_banco: list[PendienteExport] = Field(default_factory=list)
    pendientes_xubio: list[PendienteExport] = Field(default_factory=list)
    # Tabla 1 (todos los movimientos del mayor) y la pestana del extracto
    # completo. El cruce no las manda; vienen del estado de la pantalla.
    movimientos_mayor: list[MovimientoMayorExport] = Field(default_factory=list)
    movimientos_banco: list[MovimientoBancoExport] = Field(default_factory=list)
    # Saldo de apertura del mayor para la fila "Saldo Inicial" de la Tabla 1.
    # El extracto arranca su acumulado en cero (formula del spec).
    saldo_inicial_mayor: float = 0.0
    # Saldo final que informa el banco, para el pie de control. Si no llega, se
    # usa el saldo del ultimo movimiento del extracto.
    saldo_final_banco: Optional[float] = None
    encabezado: EncabezadoConciliacion = Field(default_factory=EncabezadoConciliacion)


class LineaAsientoRespuesta(BaseModel):
    """Un renglon de un asiento de ajuste: una cuenta con su Debe o su Haber."""

    cuenta: str
    # Codigo del plan de cuentas (puede ir vacio). La pantalla de revision deja
    # editarlo antes de aprobar e inyectar en Xubio.
    cuenta_codigo: str = ""
    # "banco" o "contracuenta": distingue los dos renglones.
    rol: str = ""
    detalle: str = ""
    debe: float = 0.0
    haber: float = 0.0


class AsientoRespuesta(BaseModel):
    """Un asiento de ajuste de partida doble, listo para mostrar o cargar."""

    numero: int
    fecha: Optional[date] = None
    origen: str
    # Regla de negocio que lo genero (ver reglas_conciliacion.py).
    tipo: str = ""
    regla: str = ""
    # "propuesto" | "editado" | "aprobado" | "inyectado" | "error".
    estado: str = "propuesto"
    revisar_manual: bool = False
    concepto: str = ""
    referencia: str = ""
    cuit: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    # True si Debe = Haber (la partida doble cierra).
    balancea: bool = True
    lineas: list[LineaAsientoRespuesta] = Field(default_factory=list)


class RespuestaAsientos(BaseModel):
    """Los asientos de ajuste de las partidas sin coincidencia.

    Es la vista previa de la hoja "Asientos de Ajuste" del papel de trabajo: el
    mismo calculo (asientos_ajuste.py) que arma el Excel, para que la pantalla
    no reimplemente la partida doble por su cuenta.
    """

    asientos: list[AsientoRespuesta] = Field(default_factory=list)
    total_debe: float = 0.0
    total_haber: float = 0.0


class CuentaDisponible(BaseModel):
    """Una cuenta del plan de cuentas para elegir como contracuenta en la UI."""

    codigo: str = ""
    nombre: str
    imputable: bool = True


class PartidaTemporalRespuesta(BaseModel):
    """Partida sin coincidencia que NO lleva asiento automatico.

    - Ingreso/transferencia no registrada: se asigna la cuenta del cliente.
    - Diferencia temporal del mayor: se arrastra al periodo siguiente.
    """

    origen: str
    tipo: str
    regla: str
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: str = ""
    importe: float = 0.0
    revisar_manual: bool = False


class RespuestaPropuestaAsientos(BaseModel):
    """Propuesta de asientos para la pantalla de revision y aprobacion."""

    asientos: list[AsientoRespuesta] = Field(default_factory=list)
    partidas_temporales: list[PartidaTemporalRespuesta] = Field(default_factory=list)
    total_debe: float = 0.0
    total_haber: float = 0.0
    balancea: bool = True
    cuentas_disponibles: list[CuentaDisponible] = Field(default_factory=list)


class SolicitudAprobacionAsientos(BaseModel):
    """Los asientos ya revisados que el usuario aprueba para inyectar.

    Cada asiento trae las lineas con la cuenta y el codigo que el usuario pudo
    haber editado en la pantalla.
    """

    asientos: list[AsientoRespuesta] = Field(default_factory=list)


class ResultadoAsientoInyectado(BaseModel):
    """Resultado de intentar inyectar un asiento en Xubio."""

    numero: int
    # "inyectado" | "dry_run" | "error".
    estado: str
    xubio_id: Optional[int] = None
    error: Optional[str] = None
    # El payload que se mando (o se mandaria) a Xubio, para auditar.
    payload: dict = Field(default_factory=dict)


class RespuestaAprobacionAsientos(BaseModel):
    """Resultado de aprobar e inyectar la propuesta de asientos."""

    exito: bool = True
    dry_run: bool = False
    inyectados: int = 0
    errores: int = 0
    resultados: list[ResultadoAsientoInyectado] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Afiliados (clientes) desde la web de Xubio
# ----------------------------------------------------------------------
#
# La API oficial de Xubio esta reservada a planes superiores al contratado,
# asi que la lista de afiliados se lee de la API interna del frontend web
# (core.xubio.com/ar/sba/api/cliente/clientes/findAllPaginado) usando la cookie
# de sesion del navegador (xubio_web_client.py). Los nombres de campo imitan
# los que manda Xubio a proposito: inventar un mapeo propio entre nombres solo
# daria otra superficie donde romperse cuando Xubio cambie algo.


class Afiliado(BaseModel):
    """Un cliente/afiliado tal como lo devuelve clientes/findAllPaginado."""

    # La web manda decenas de campos; la app se queda con los que usa y
    # descarta el resto sin quejarse.
    model_config = ConfigDict(extra="ignore")

    id: int
    organizacionId: int
    organizacionNombre: str
    cuit: Optional[str] = None
    categoriaFiscal: Optional[str] = None
    activo: int = 1
    esProveedor: int = 0
    email: Optional[str] = None
    # La web manda telefono nulo en varios registros, no solo en los que no
    # tiene dato: el campo tiene que aceptar None y no solo "".
    telefono: Optional[str] = None
    localidad: Optional[str] = None
    provincia: Optional[str] = None
    pais: Optional[str] = None
    cuentaVenta: Optional[str] = None


class RespuestaAfiliados(BaseModel):
    exito: bool
    cantidad: int
    # La lista completa ya paginada: el backend llama a todas las paginas que
    # haga falta y aca llega entera.
    datos: list[Afiliado]


class Estudio(BaseModel):
    """Un estudio/empresa a los que puede entrar la cuenta logueada de Xubio.

    La cuenta de un estudio contable habilita decenas de empresas (un cliente
    por estudio). El selector de la barra superior de la web de Xubio las
    lista; cada una entra por un tenant distinto (`/NXV/Relogin?tenant=tnt_XX`).

    `origen` dice de donde salio la entrada:

      * "empresa": del selector de la barra superior (la fuente de verdad del
        orden y de los tenants, pero sin CUIT).
      * "cliente": del catalogo de afiliados de la contabilidad (trae CUIT y
        organizacionId, que es el codigo con el que el Libro Mayor filtra).
      * "ambos": se matcheo una contra la otra por nombre normalizado. Es lo
        que se devuelve cuando las dos fuentes estan disponibles.
    """

    model_config = ConfigDict(extra="ignore")

    # Identidad dentro de la app. Prefija el origen para que la misma clave no
    # pueda designar dos cosas distintas ("empresa:tnt_123456").
    clave: str
    nombre: str
    origen: Literal["empresa", "cliente", "ambos"]
    # Del selector superior: con esto se cambia de estudio en la web.
    tenant: Optional[str] = None
    # Del catalogo de clientes: el codigo con el que el Libro Mayor filtra
    # (p_OrganizacionReportCode) y el id del cliente en Xubio.
    organizacion_id: Optional[int] = None
    cuit: Optional[str] = None
    # "empresa" (la del selector, que es la que tiene abierta la sesion) o
    # "seleccion" (la que elegio el usuario en la app).
    es_actual: bool = False
    activo: bool = True


class SolicitudEstudio(BaseModel):
    """El estudio que el usuario elige en el selector de la barra superior."""

    clave: str


class RespuestaEstudios(BaseModel):
    """Lo que muestra el selector: el listado y cual esta activo."""

    exito: bool
    # False si no hay XUBIO_WEB_TOKEN ni XUBIO_WEB_COOKIE: sin eso no se puede
    # bajar nada y el selector tiene que ofrecer el login.
    configurada: bool
    # True si el catalogo de estudio ya bajo alguna vez (puede quedar vacio si
    # la cuenta no tiene empresas cargadas).
    catalogo_cargado: bool
    # El nombre de la empresa que tiene abierta la sesion de Xubio ahora, si
    # el bot lo pudo leer del selector superior.
    empresa_en_sesion: Optional[str] = None
    # El estudio elegido en la app (sobrevive a reinicios del backend).
    actual: Optional[Estudio] = None
    estudios: list[Estudio] = Field(default_factory=list)
    # Motivo por el que no se pudo bajar el catalogo, si no se pudo.
    aviso: Optional[str] = None


class SolicitudCruceAfiliados(BaseModel):
    movimientos: list[MovimientoBancario]
    # Si el frontend ya tiene la lista descargada la manda aca y el backend no
    # vuelve a llamar a la web de Xubio.
    afiliados: list[Afiliado] = Field(default_factory=list)


class MovimientoMayorClasificable(BaseModel):
    """Una fila del lado de Xubio, para clasificarla contra los afiliados.

    El cruce devuelve los pendientes del mayor como {fecha, concepto, debe,
    haber, importe} y los pares con mas campos (concepto_banco, saldo, etc.).
    Este schema acepta cualquiera de las dos formas: lo que no se reconoce se
    descarta, porque lo unico que se lee es el texto de la fila.
    """

    model_config = ConfigDict(extra="ignore")

    fecha: Optional[date] = None
    concepto: str = ""
    debe: float = 0.0
    haber: float = 0.0
    importe: Optional[float] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class SolicitudClasificarMayor(BaseModel):
    """Clasifica los movimientos del Libro Mayor por afiliado, sin cruzar nada.

    Alimenta el filtro "Empresa" de la bandeja derecha: el mismo cruce puro de
    /cruzar-afiliados, pero para las filas del mayor en vez de las del banco.
    """

    movimientos: list[MovimientoMayorClasificable]
    # Igual que en SolicitudCruceAfiliados: si el frontend ya bajo la lista la
    # manda aca y el backend no vuelve a la web de Xubio.
    afiliados: list[Afiliado] = Field(default_factory=list)


class CruceAfiliadoMovimiento(BaseModel):
    indice: int
    afiliado: Optional[Afiliado] = None
    # 'cuit' o 'nombre'; None cuando la fila no encontro a nadie.
    metodo: Optional[str] = None


class RespuestaCruceAfiliados(BaseModel):
    exito: bool
    resumen: dict
    # Una entrada por movimiento, en el mismo orden: datos[i] corresponde a
    # movimientos[i], asi el frontend puede superponerla a su tabla sin
    # buscar.
    datos: list[CruceAfiliadoMovimiento]


class SolicitudLoginXubio(BaseModel):
    """Credenciales del login de la pantalla de conciliacion.

    El backend las guarda en backend/.env (XUBIO_EMAIL / XUBIO_PASSWORD) y las
    usa el bot para renovar la sesion de la web de Xubio con el navegador
    visible. No se versionan: quedan solo en el .env local.
    """

    email: str
    password: str


class AfiliadoConXubio(BaseModel):
    """Un afiliado del catalogo del bot: existe en Xubio (tiene_xubio=True).

    `afiliado_id` es el id local del afiliado (o el id de Xubio cuando no se
    paso una lista local) y `xubio_cliente_id` es el id de la cuenta en Xubio,
    el que se manda para pedir el Libro Mayor de ese cliente.
    """
    afiliado_id: str
    nombre: str
    cuit: Optional[str] = None
    xubio_cliente_id: int
    tiene_xubio: bool = True


class SolicitudBotXubio(BaseModel):
    """Entrada del pipeline del bot (POST /xubio/bot/sincronizar).

    Sin `afiliado_id` devuelve solo el catalogo de afiliados con Xubio. Con un
    afiliado seleccionado hace ademas el fetch del Libro Mayor del periodo.

    `afiliados` es la lista local opcional: si viene, se cruza por CUIT contra
    Xubio y solo se devuelven los que coinciden (el resto queda tiene_xubio
    False y no se lista). Sin lista local, todos los activos de Xubio entran.
    """
    desde: Optional[str] = None
    hasta: Optional[str] = None
    afiliado_id: Optional[str] = None
    organizacion_report_code: Optional[str] = None
    afiliados: list[Afiliado] = Field(default_factory=list)


class RespuestaBotXubio(BaseModel):
    """Contrato de salida del pipeline del bot de Xubio.

    `status` es SUCCESS | FALLBACK_MANUAL | ERROR. FALLBACK_MANUAL significa que
    hay que pedir el archivo a mano (sin sesion, timeout o afiliado sin cuenta
    en Xubio); ERROR es una falla inesperada.
    """
    status: str
    afiliados_con_xubio: list[AfiliadoConXubio] = Field(default_factory=list)
    data_mayor_normalizada: list[dict] = Field(default_factory=list)
    execution_logs: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None


# ----------------------------------------------------------------------
# Conciliación Avanzada (FO 02-03 completo)
# ----------------------------------------------------------------------

class MovimientoBancoCrudo(BaseModel):
    """Extracto crudo (17 columnas) tal como viene del Home Banking / ICBC.

    Se usa solo para enriquecer: buscar CUIT, CBU, Nombre, Cod Concepto, Canal,
    Banco emisor cuando el matching automático no identifica al tercero.
    """
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    fecha_contable: Optional[date] = Field(None, alias="Fecha contable")
    cod_concepto: Optional[str] = Field(None, alias="Cod de Concepto")
    concepto: str = Field("", alias="Concepto")
    debito: float = Field(0.0, alias="Debito en $")
    credito: float = Field(0.0, alias="Credito en $")
    saldo: float = Field(0.0, alias="Saldo en $")
    info_complementaria: Optional[str] = Field(None, alias="Informacion Complementaria")
    nro_cheque: Optional[str] = Field(None, alias="Nro de cheque")
    sucursal_origen: Optional[str] = Field(None, alias="Sucursal Origen")
    canal: Optional[str] = Field(None, alias="Canal")
    banco: Optional[str] = Field(None, alias="Banco")
    cbu_alias: Optional[str] = Field(None, alias="CBU/Alias")
    tipo_trf: Optional[str] = Field(None, alias="Tipo trf")
    referencia: Optional[str] = Field(None, alias="Referencia")
    nombre: Optional[str] = Field(None, alias="Nombre")
    tipo_doc: Optional[str] = Field(None, alias="Tipo doc")
    nro_doc: Optional[str] = Field(None, alias="Nro doc")

    _fecha = field_validator("fecha_contable", mode="before")(_normalizar_fecha)


class ConciliadoAvanzado(BaseModel):
    """Un par conciliado con toda la trazabilidad."""
    fecha: Optional[date] = None
    concepto_banco: str = ""
    concepto_mayor: str = ""
    referencia_banco: Optional[str] = None
    comprobante_mayor: Optional[str] = None
    importe_banco: float = 0.0
    importe_mayor: float = 0.0
    debe_banco: float = 0.0
    haber_banco: float = 0.0
    debe_mayor: float = 0.0
    haber_mayor: float = 0.0
    saldo_banco: float = 0.0
    saldo_mayor: float = 0.0
    categoria: str = ""
    cuadra: bool = True
    diferencia_dias: int = 0
    cuit: Optional[str] = None
    cbu: Optional[str] = None
    nombre_tercero: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class AjusteContable(BaseModel):
    """Movimiento solo en banco que genera asiento de ajuste (gasto, impuesto,
    retencion o debito automatico)."""
    origen: str = "ajuste_contable"
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    # Regla de negocio aplicada (reglas_conciliacion.py).
    tipo: str = ""
    regla: str = ""
    accion: str = ""
    revisar_manual: bool = False
    debito: float = 0.0
    credito: float = 0.0
    importe: float = 0.0
    saldo: float = 0.0
    categoria: str = ""
    cuit: Optional[str] = None
    cbu: Optional[str] = None
    nombre_tercero: Optional[str] = None
    cod_concepto: Optional[str] = None
    canal: Optional[str] = None
    banco_emisor: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class PartidaPendienteBanco(BaseModel):
    """Movimiento en banco sin par que NO lleva asiento automatico.

    Son las acreditaciones / transferencias no registradas: se marcan para
    revision y se les asigna la cuenta del cliente.
    """
    origen: str = "pendiente_banco"
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    tipo: str = ""
    regla: str = ""
    accion: str = ""
    revisar_manual: bool = False
    debito: float = 0.0
    credito: float = 0.0
    importe: float = 0.0
    saldo: float = 0.0
    categoria: str = ""
    cuit: Optional[str] = None
    cbu: Optional[str] = None
    nombre_tercero: Optional[str] = None
    cod_concepto: Optional[str] = None
    canal: Optional[str] = None
    banco_emisor: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class PartidaPendienteMayor(BaseModel):
    """Movimiento en mayor sin par en banco (diferencia temporal, sin asiento)."""
    origen: str = "pendiente_mayor"
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    comprobante: Optional[str] = None
    tipo: str = ""
    regla: str = ""
    accion: str = ""
    revisar_manual: bool = False
    debe: float = 0.0
    haber: float = 0.0
    importe: float = 0.0
    saldo: float = 0.0
    categoria: str = ""
    documento: Optional[str] = None
    cuenta: Optional[str] = None
    organizacion: Optional[str] = None
    descripcion: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class PartidasPendientesUnion(BaseModel):
    """Union type discriminado por 'origen'."""
    origen: str
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    comprobante: Optional[str] = None
    tipo: str = ""
    regla: str = ""
    accion: str = ""
    revisar_manual: bool = False
    debe: float = 0.0
    haber: float = 0.0
    importe: float = 0.0
    saldo: float = 0.0
    categoria: str = ""
    # campos opcionales según origen
    cuit: Optional[str] = None
    cbu: Optional[str] = None
    nombre_tercero: Optional[str] = None
    cod_concepto: Optional[str] = None
    canal: Optional[str] = None
    banco_emisor: Optional[str] = None
    documento: Optional[str] = None
    cuenta: Optional[str] = None
    organizacion: Optional[str] = None
    descripcion: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class CuadroControl(BaseModel):
    """Cuadro de control FO 02-03."""
    ingresos: dict
    egresos: dict
    ajustes_contables: dict
    partidas_pendientes: dict
    conciliados: dict


class TablaDinamicaGasto(BaseModel):
    """Una fila del cuadro de gastos bancarios: un concepto con sus sumas.

    `suma_debito` va en negativo (es una salida) y `suma` es el valor absoluto,
    que solo se usa para ordenar de mayor a menor.
    """
    concepto: str
    suma_credito: float = 0.0
    suma_debito: float = 0.0
    suma: float
    cantidad: int
    porcentaje: float
    porcentaje_acumulado: float


class ActaConciliacion(BaseModel):
    """Valores del acta de conciliación (puente mayor -> banco).

    `egresos_no_registrados` y `transferencias_transito` ya vienen con el signo
    negativo con el que se muestran en el informe.
    """
    saldo_libro_mayor: float = 0.0
    ingresos_no_registrados: float = 0.0
    egresos_no_registrados: float = 0.0
    cheques_no_cobrados: float = 0.0
    transferencias_transito: float = 0.0
    saldo_banco: float = 0.0
    diferencia: float = 0.0


class ReporteMarkdown(BaseModel):
    """Reporte listo para pegar: cuadro de gastos y acta, ambos en Markdown."""
    cuadro_gastos: str = ""
    acta_conciliacion: str = ""
    acta: ActaConciliacion = Field(default_factory=ActaConciliacion)



class EstadisticasConciliacion(BaseModel):
    total_movimientos_banco: int
    total_movimientos_mayor: int
    conciliados: int
    ajustes_contables: int
    pendientes_banco: int
    pendientes_mayor: int
    porcentaje_conciliado: float


class RespuestaConciliacionAvanzada(BaseModel):
    exito: bool = True
    conciliados: list[ConciliadoAvanzado] = Field(default_factory=list)
    ajustes_contables: list[AjusteContable] = Field(default_factory=list)
    partidas_pendientes: list[PartidasPendientesUnion] = Field(default_factory=list)
    cuadro_control: CuadroControl
    tabla_dinamica_gastos: list[TablaDinamicaGasto] = Field(default_factory=list)
    estadisticas: EstadisticasConciliacion
    reporte_markdown: ReporteMarkdown = Field(default_factory=ReporteMarkdown)


class SolicitudConciliacionAvanzada(BaseModel):
    movimientos_banco: list[MovimientoBancario]
    movimientos_mayor: list[dict]
    extracto_crudo: Optional[list[MovimientoBancoCrudo]] = None
    tolerancia_dias: int = 3