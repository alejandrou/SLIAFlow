# Análisis: SLIAFlow como base para la visualización STRATUM en 3D Slicer

> Current Slicer-module mock drafts: [plain-language overview](STRATUM_SLICER_MODULE_OVERVIEW.md) and [UC1 technical draft](STRATUM_SLICER_UC1_TECHNICAL_DRAFT.md). The analysis below is retained as supporting background.

> Nota de referencia. Fecha del análisis: 2026-07-31.
> Documento de análisis, no una decisión aceptada. Las decisiones arquitectónicas
> requieren un ADR en `docs/architecture/decisions/`. Las tareas propuestas en la
> sección 12 son una propuesta, no un backlog activado.

## Contexto del análisis

- SLIAFlow es un prototipo y conserva provisionalmente ese nombre.
- Runtime declarado por el propietario: 3D Slicer oficial 5.13.0, compilación 2026-07-02.
- AcquisitionSystemApp y UC2 permanecen fuera de Slicer.
- Un servicio externo enviará a Slicer, mediante OpenIGTLink, una imagen RGB producida por UC2.
- Inicialmente todo se ejecuta en localhost.
- UC2 genera una imagen RGB simple, no un mapa escalar de profundidad.
- No se integra todavía el algoritmo dentro del proceso de Slicer.
- Se buscan tareas pequeñas, revisables y no desechables.

---

## Resumen ejecutivo

El repositorio está bien posicionado para lo que se persigue, pero por una razón
distinta de la esperable: su valor no está en el código del módulo (que hoy son dos
herramientas de diagnóstico), sino en la infraestructura de ciclo de vida, tests y
políticas, que ya encaja con un algoritmo externo.

Tres hallazgos que condicionan todo lo demás:

1. **No hay ni una línea de OpenIGTLink en el repositorio.** Verificado sobre los 60
   archivos versionados. Se parte de cero en recepción.
2. **El Slicer configurado no es el declarado.** `config/local.json` apunta a
   `C:/stratum/apps/SR/Slicer-build/Slicer.exe`, una compilación propia desde `source/`
   (rev `0f71972e42`, 2026-06-23, Slicer 5.13.0). Listando `apps/SR/`, sus extensiones
   integradas son BRAINSTools, CompareVolumes, LandmarkRegistration,
   MultiVolumeExplorer/Importer, SimpleFilters y SurfaceToolbox: no incluye
   OpenIGTLink, y una compilación propia no puede instalar extensiones binarias del
   Extension Manager. El Slicer oficial 5.13.0 sí puede. Hoy, por tanto, el runner de
   tests y el flujo manual usarían Slicers distintos.
3. **`.ai/policies/algorithm-boundary-policy.md` ya está escrito para este caso.** Dice
   literalmente *"External algorithm results must be validated before they affect
   user-visible or persisted state"*. Fue redactado pensando en un proveedor
   in-process, pero aplica sin cambios a un resultado que llega por socket. No hay que
   tocarlo.

---

## 1. Estado actual del módulo SLIAFlow

Extensión estándar generada con la plantilla de Slicer, renombrada en el commit `986396b`.

### Punto de entrada

`extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`

`class SLIAFlow(ScriptedLoadableModule)`. Solo metadatos: título, categoría `SLIAFlow`,
`helpText`, `acknowledgementText`. Sin lógica, correcto según
`docs/slicer/slicer_module_architecture.md`.

### Lógica

`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py` (185 líneas)

`class SLIAFlowLogic(ScriptedLoadableModuleLogic)` con dos capacidades:

- `collectEnvironmentReport()` / `formatEnvironmentReport()` — versión de Slicer,
  Python, imports de `slicer/vtk/qt/ctk`, paquetes `numpy/SimpleITK`, contador de nodos.
  Diagnóstico puro.
- `inspectVolumeMetadata(volumeNode)` / `formatVolumeMetadataReport()` — dimensiones,
  spacing, origen RAS, matriz IJK→RAS, tipo escalar, número de vóxeles, volumen estimado
  por vóxel.

Ambas son pasivas y sin efectos secundarios: no mutan la escena, devuelven `dict` con
`summaryStatus` ∈ {`PASS`, `WARN`, `FAIL`}. Ese contrato es exactamente lo que necesita
una capa de validación.

### Estado

`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py` (9 líneas)

`@parameterNodeWrapper class SLIAFlowParameterNode` con un único campo
`inputVolumeNode: slicer.vtkMRMLVolumeNode | None`.

### Widget

`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py` (126 líneas)

`class SLIAFlowWidget(ScriptedLoadableModuleWidget, VTKObservationMixin)`. Carga el
`.ui`, gestiona el ciclo de vida del parameter node (`initializeParameterNode`,
`setParameterNode`, `onSceneStartClose`, `onSceneEndClose`), sincronización bidireccional
con guarda anti-recursión `_updatingGUIFromParameterNode`, y `_setSummaryState` /
`_setVolumeMetadataState` que pintan PASS verde / WARN ámbar / FAIL rojo.

### UI

`extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`

Dos `ctkCollapsibleButton` ("Environment Check", "Volume Metadata"), un
`qMRMLNodeComboBox`, dos botones, dos etiquetas de estado, dos `QPlainTextEdit` de solo
lectura.

### Tests

`extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`

5 tests con datos sintéticos vía `_createSyntheticVolume()`. Adaptador de descubrimiento
en `extensions/SLIAFlow/SLIAFlow/Testing/Python/SLIAFlowModuleTest.py`, registrado como
`py_SLIAFlowModuleTest`.

### Tooling

`scripts/development/run-slicer-tests.ps1` (lanza Slicer con `--testing
--no-main-window --disable-cli-modules`), `scripts/development/run-python-quality.ps1`,
Ruff `py312` + Pyright.

### Lo que no existe

Red, algoritmo, nodos de resultado, control de layout, provenance, etiquetado no-clínico
visible.

---

## 2. Partes reutilizables

### Reutilización directa, sin cambios

| Elemento | Para qué sirve en STRATUM |
|---|---|
| `SLIAFlowParameterNode` | Añadir `resultVolumeNode` junto a `inputVolumeNode` (2 líneas) |
| Ciclo de vida de observadores en `SLIAFlowWidget` | Patrón exacto para observar nodos IGTL sin fugas tras Reload |
| `_setSummaryState()` + convención PASS/WARN/FAIL | Presentación de estado de conexión y de validación |
| `VTKObservationMixin.addObserver/removeObservers` | Base de la detección de resultados (§9) |
| `_createSyntheticVolume()` | Semilla de los fixtures RGB sintéticos (§11) |
| `run-slicer-tests.ps1` + registro CTest | Ya funciona headless; no rehacer |
| `.ai/` completo (políticas, workflows, plantilla) | Marco de gobernanza; `algorithm-boundary-policy.md` aplica tal cual |

### Reutilización con extensión mínima

`SLIAFlowLogic.inspectVolumeMetadata()` es la base natural de la validación, pero tiene
dos huecos concretos para RGB:

- No reporta `imageData.GetNumberOfScalarComponents()`. Sin ese dato no puede distinguir
  una imagen RGB (3 componentes) de una escalar, que es justo la discriminación clave de
  UC2.
- `estimatedVoxelVolumeMm3` (`SLIAFlowLogic.py:150`) carece de sentido para una imagen 2D
  de dimensiones `(W, H, 1)`.

Un detalle que ya está bien y no hay que tocar: el combo box en `SLIAFlowWidget.py:30` ya
acepta `vtkMRMLVectorVolumeNode`, y `inputVolumeNode` está tipado como
`vtkMRMLVolumeNode | None`, que es la clase padre. Los volúmenes RGB recibidos por IGTL
serán seleccionables sin ningún cambio.

### No reutilizable en la ruta STRATUM

El panel "Environment Check" y `collectEnvironmentReport()` son diagnóstico de
desarrollo. Conservarlos, pero no forman parte del flujo.

---

## 3. Tareas experimentales: cerrar, sustituir o conservar

| Tarea | Disposición | Motivo |
|---|---|---|
| BSSL-001 … BSSL-004 (completadas) | **Conservar** | Infraestructura, no experimentos. Son el historial que sostiene el resto. |
| BSSL-005 | **Conservar** | El parameter node es la base sobre la que se construye STRATUM. |
| BSSL-006 *Define algorithm provider boundary* | **Sustituir** | Su premisa —"a provider protocol or interface", un mock invocable desde Python in-process— queda obsoleta: UC2 vive fuera del proceso de Slicer. La frontera ya no es un protocolo Python, es un contrato de transporte (tipo de mensaje IGTL, nombre de dispositivo, forma y dtype). Lo que sí sobrevive intacto es su mitad de validación: *"Validate results before scene mutation, persistence, or successful display"*. |
| BSSL-007 *First mock vertical slice* | **Sustituir** | La idea del "vertical slice" es correcta; el mecanismo no. El "mock provider" ya no es una clase Python: es un emisor externo sintético. El slice pasa a ser *recibir → validar → presentar lado a lado*. |
| BSSL-008 *Persist and summarize results* | **Conservar, reformular y posponer** | La pregunta que plantea (propiedad del resultado en MRML, provenance, resultados obsoletos) es real y seguirá siéndolo. Pero no se puede responder antes de que existan resultados. Renumerar al final de la nueva secuencia. |

Sobre la nomenclatura: el prefijo `BSSL` ya no describe nada. Se sugiere `STR-###` para
el nuevo backlog, dejando los `BSSL-*` intactos como registro histórico.

---

## 4. Cómo recibir una imagen OpenIGTLink con herramientas estándar

La herramienta es **SlicerOpenIGTLink**, módulo `OpenIGTLinkIF`
(`scm_url: https://github.com/openigtlink/SlicerOpenIGTLink.git`, categoría IGT, tier 5
en el catálogo). Se instala desde el Extension Manager.

### Flujo en Python

`slicer.vtkMRMLIGTLConnectorNode` queda expuesto tras instalar la extensión:

```python
connector = slicer.vtkMRMLIGTLConnectorNode()
connector.SetName("STRATUM_Connector")
slicer.mrmlScene.AddNode(connector)
connector.SetTypeServer(18944)        # o SetTypeClient("localhost", 18944)
connector.Start()                      # Stop() para cerrar
```

Este es el patrón real usado en producción: ver
`slicer-extensions/aigt/HerniaRepairTutor/RecordHerniaData/RecordHerniaData.py:152-195`,
que monta exactamente cuatro conectores RGB/depth sobre localhost en los puertos
18944-18947.

### Recomendación

Slicer como **servidor** (`SetTypeServer`), servicio externo como cliente. Así Slicer no
necesita saber cuándo arranca el servicio, y el servicio conecta cuando tiene un
resultado. Puerto > 1024; 18944 es el estándar de facto.

### Qué ocurre al llegar un mensaje IMAGE

En `vtkMRMLIGTLConnectorNode::CreateNewMRMLNodeForDevice()`
(`OpenIGTLinkIF/MRML/vtkMRMLIGTLConnectorNode.cxx`), el conector lee
`content.image->GetNumberOfScalarComponents()` y bifurca. En cada mensaje posterior,
`ProcessIncomingDeviceModifiedEvent()` aplica la transformada IJK→RAS del mensaje, hace
`SetAndObserveImageData()` y fuerza en el `vtkImageData` spacing (1,1,1), origen (0,0,0)
y matriz de dirección identidad, para no duplicar la geometría que ya vive en el
IJKToRAS del nodo.

### El nombre del dispositivo IGTL es el contrato

El nodo MRML se nombra con el device name del mensaje
(`volumeNode->SetName(deviceName.c_str())`), y en el siguiente mensaje se reutiliza el
nodo existente que coincida por nombre y clase. Conviene definir dos nombres estables
desde el principio, por ejemplo `STRATUM_INPUT` y `STRATUM_UC2`, y no cambiarlos: son la
API.

---

## 5. ¿Basta OpenIGTLinkIF para el primer MVP, sin tocar SLIAFlow?

**Sí, y es lo recomendable.** El MVP cero no necesita ni una línea de código nuevo en
SLIAFlow:

1. Instalar SlicerOpenIGTLink en el Slicer oficial 5.13.0.
2. Módulo `OpenIGTLinkIF` → botón `+` → tipo Server, puerto 18944 → marcar *Active*.
3. El servicio externo envía dos mensajes IMAGE con device names distintos.
4. Los dos `vtkMRMLVectorVolumeNode` aparecen solos en la escena, con display node y
   color map por defecto.
5. Layout lado a lado desde la barra de herramientas y asignación de volúmenes desde el
   módulo Volumes, a mano.

**SlicerIGT no hace falta.** Es para tracking, transformadas y navegación quirúrgica; no
aporta nada a recibir y mostrar una imagen. No instalarlo para el MVP.

### Dos condiciones a verificar antes

Ambas derivadas del hallazgo 2 del resumen:

- Que el Extension Manager ofrezca SlicerOpenIGTLink para la revisión exacta del build
  5.13.0 del 2026-07-02. Las extensiones se sirven por revisión; una preview reciente
  puede no tener build disponible.
- Que se decida cuál es el Slicer objetivo. Hoy `config/local.json` apunta al build
  propio de `apps/SR`, que no puede instalar la extensión. O bien se apunta la
  configuración al Slicer oficial, o bien se compila la extensión contra `apps/SR`, pero
  conviene decidirlo antes de escribir tests que dependan de ello.

### Lo que el MVP manual no da

Y que justifica la sección 6: reproducibilidad (cada sesión es clicar de nuevo),
validación (una imagen corrupta se muestra igual de bien que una correcta), correlación
entrada↔resultado, etiquetado no-clínico, y tests automáticos.

---

## 6. Valor de un módulo propio, después

Un módulo SLIAFlow orientado a STRATUM aporta cinco cosas que `OpenIGTLinkIF` no puede
aportar, porque no es su trabajo:

1. **Escena determinista de un clic.** Layout correcto, imagen de entrada en la vista
   izquierda, resultado UC2 en la derecha, mismo zoom, misma orientación. Siempre igual.
2. **Frontera de validación**, que es literalmente lo que exige
   `.ai/policies/algorithm-boundary-policy.md`: comprobar 3 componentes, dtype
   `unsigned char`, dimensiones no vacías y coherentes con la entrada, nombre de
   dispositivo esperado, y negarse a presentarlo como éxito si algo falla. Sin esto, un
   resultado malformado se muestra idéntico a uno correcto.
3. **Etiquetado explícito de prototipo / no clínico**, exigido por
   `.ai/policies/medical-data-policy.md`: *"Outputs must clearly identify mock or demo
   data and must not imply clinical validity"*. Un `vtkMRMLVectorVolumeNode` genérico no
   lo comunica.
4. **Correlación y frescura.** Qué resultado corresponde a qué entrada, y detectar cuándo
   el resultado mostrado es obsoleto respecto a la entrada actual.
5. **Tests automáticos headless.** La GUI de `OpenIGTLinkIF` no es testeable; una clase
   `Logic` sí, y el runner que la ejecuta ya existe.

Y la regla inversa, igual de importante: **el módulo orquesta, no reimplementa el
transporte.** Nada de sockets propios.

---

## 7. Vista lado a lado automática

Hay un layout integrado, `vtkMRMLLayoutNode::SlicerLayoutSideBySideView = 29`
(`Libs/MRML/Core/vtkMRMLLayoutNode.h:151`):

```python
slicer.app.layoutManager().setLayout(29)
```

Pero da Red (Axial) + Yellow (Sagittal). Para comparar dos imágenes 2D se quiere la
misma orientación en ambas, así que conviene un layout propio vía `AddLayoutDescription`:

```python
customLayout = """
<layout type="horizontal" split="true">
  <item><view class="vtkMRMLSliceNode" singletontag="Red">
    <property name="orientation" action="default">Axial</property>
    <property name="viewlabel" action="default">IN</property>
  </view></item>
  <item><view class="vtkMRMLSliceNode" singletontag="Yellow">
    <property name="orientation" action="default">Axial</property>
    <property name="viewlabel" action="default">UC2</property>
  </view></item>
</layout>
"""
layoutManager = slicer.app.layoutManager()
layoutManager.layoutLogic().GetLayoutNode().AddLayoutDescription(701, customLayout)
layoutManager.setLayout(701)
```

Los IDs integrados están por debajo de 100; usar uno alto
(`Docs/developer_guide/script_repository/gui.md:613-644`).

### Asignación de volúmenes: no usar `slicer.util.setSliceViewerLayers()`

Su implementación (`Base/Python/slicer/util.py:728-740`) itera sobre *todos* los
`vtkMRMLSliceCompositeNode` de la escena y pone el mismo volumen en todas las vistas,
justo lo contrario de lo necesario. Hay que ir por vista:

```python
lm = slicer.app.layoutManager()
for viewName, node in (("Red", inputNode), ("Yellow", resultNode)):
    widget = lm.sliceWidget(viewName)
    widget.sliceLogic().GetSliceCompositeNode().SetBackgroundVolumeID(node.GetID())
    widget.mrmlSliceNode().RotateToVolumePlane(node)   # alinea el plano con la imagen
    widget.sliceLogic().FitSliceToAll()
```

`RotateToVolumePlane` está en `vtkMRMLSliceNode.h:447`, `FitSliceToAll` en
`vtkMRMLSliceLogic.h:259`.

### Enlazado

`vtkMRMLSliceCompositeNode` tiene `SetLinkedControl` (`.h:136-138`), por defecto 0. Si
entrada y resultado comparten geometría, ponerlo a 1 hace que zoom y desplazamiento se
muevan juntos, que es lo deseable para comparar.

---

## 8. Qué nodo MRML se crearía

Depende del número de componentes de la imagen, decidido en
`CreateNewMRMLNodeForDevice()`:

| Caso | Nodo de datos | Nodo de display |
|---|---|---|
| **RGB (3 comp.) — el caso de UC2** | `vtkMRMLVectorVolumeNode` | `vtkMRMLVectorVolumeDisplayNode` con `SetDefaultColorMap()` |
| Escalar (1 comp.) | `vtkMRMLScalarVolumeNode` | `vtkMRMLScalarVolumeDisplayNode` con color table `Grey` |
| VIDEO + `SetUseStreamingVolume(true)` | `vtkMRMLStreamingVolumeNode` | — (no aplica al MVP) |

En ambos casos el nodo lleva `SetDescription("Received by OpenIGTLink")`, un marcador
útil para filtrar.

### Consecuencias prácticas

- Una imagen RGB 2D llega con dimensiones `(W, H, 1)` y 3 componentes `unsigned char`.
  `slicer.util.arrayFromVolume()` devuelve orden KJI, es decir shape `(1, H, W, 3)`.
- `inputVolumeNode: slicer.vtkMRMLVolumeNode | None` en el parameter node ya acepta
  vector volumes por herencia. Sin cambios.
- El único ajuste necesario en la lógica existente es reportar
  `GetNumberOfScalarComponents()`, hoy ausente.

---

## 9. Detectar la llegada de un nuevo resultado

Tres niveles, del más desacoplado al más acoplado. Se recomienda el (a) como mecanismo
principal.

### (a) Observar el nodo de volumen — recomendado

```python
self.addObserver(resultNode, slicer.vtkMRMLVolumeNode.ImageDataModifiedEvent, self.onResultReceived)
```

`ImageDataModifiedEvent = 18001` (`Libs/MRML/Core/vtkMRMLVolumeNode.h:204`). Funciona de
forma fiable por un detalle no obvio que conviene conocer: igtlio **reutiliza el mismo
puntero `vtkImageData`** entre mensajes, y `vtkMRMLVolumeNode::SetAndObserveImageData()`
retorna temprano si recibe el puntero ya instalado. Pero en la primera instalación se
registra un `vtkEventForwarderCommand` sobre el `vtkCommand::ModifiedEvent` del propio
`vtkImageData`, que lo reenvía al trivial producer y hace que el nodo emita
`ImageDataModifiedEvent` igualmente. Además, `ProcessIncomingDeviceModifiedEvent()` llama
a `volumeNode->Modified()` explícitamente.

Ventaja decisiva: **no requiere importar ninguna clase de OpenIGTLink**. SLIAFlow observa
MRML y punto.

### (b) Detectar el nodo que aún no existe

```python
self.addObserver(slicer.mrmlScene, slicer.vtkMRMLScene.NodeAddedEvent, self.onNodeAdded)
```

Filtrar por clase y nombre esperado. También independiente de OpenIGTLink.

### (c) Eventos del conector — solo para estado de conexión

`slicer.vtkMRMLIGTLConnectorNode.ConnectedEvent` (118944), `DisconnectedEvent` (118945),
`NewDeviceEvent` (118949, invocado con el nodo MRML como callData). Patrón real en
`slicer-extensions/SlicerIGT/Guidelet/GuideletLib/Guidelet.py:631-632`.

**Aviso concreto:** `DeviceModifiedEvent = 118950` está declarado en el enum de
`vtkMRMLIGTLConnectorNode.h:63` pero **nunca se invoca** en el `.cxx`. No construir nada
sobre él.

### Dos cautelas de diseño

- Poner los observadores en la `Logic`, no en el `Widget`, para poder testearlos headless
  (el widget solo observa a la logic).
- Aunque UC2 sea petición/respuesta y de baja frecuencia, contabilizar un identificador
  de resultado monótono para no reprocesar el mismo frame.

---

## 10. Separación estricta de las cinco capas

Propuesta de mapeo a archivos bajo `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/`, con
dependencias siempre hacia abajo.

### 1 · Recepción

No vive en SLIAFlow. Es `OpenIGTLinkIF`. Regla dura: **ningún archivo de lógica de
SLIAFlow importa `vtkMRMLIGTLConnectorNode`.** Si más adelante se quiere el botón de
conveniencia "crear y arrancar conector", aislarlo en un único adaptador
(`SLIAFlowIgtlAdapter.py`) con comprobación de capacidad:

```python
if not hasattr(slicer, "vtkMRMLIGTLConnectorNode"):
    return {"summaryStatus": "WARN", "summaryMessage": "OpenIGTLinkIF is not installed."}
```

Así el módulo carga y los tests corren sin la extensión instalada.

### 2 · Presentación

`SLIAFlowPresentation.py`. Layout, composite nodes, orientación, etiquetas. Sin red, sin
validación, sin decisiones.

**Restricción concreta:** `scripts/development/run-slicer-tests.ps1:55` lanza Slicer con
`--no-main-window`, y `slicer.app.layoutManager()` puede ser `None` en ese modo; el
propio `slicer.util.setSliceViewerLayers` lo protege con `if layoutManager is not None`
(`util.py:758`). Diseñar esta capa para operar sobre nodos MRML siempre que sea posible,
y verificar en un spike corto si los composite nodes Red/Yellow existen sin ventana
principal; si no, esta capa se valida manualmente y no en CI.

### 3 · Algoritmo

Fuera del proceso, íntegramente. El "contrato" es documentación, no código: tipo de
mensaje IMAGE, nombres de dispositivo, 3 componentes `uint8`, convención de coordenadas,
quién es servidor. Debe vivir en un ADR bajo `docs/architecture/decisions/`, hoy vacío
salvo el `.gitkeep`.

### 4 · Validación

`SLIAFlowValidation.py`. Funciones puras sobre `vtkImageData`/numpy. Sin Qt, sin red, **sin
mutar la escena**. Devuelve el mismo contrato `dict` con
`summaryStatus`/`summaryMessage`/`reportText` que ya usa `inspectVolumeMetadata`, para que
el widget existente lo pinte sin cambios. Es la capa más testeable y la que cumple
`algorithm-boundary-policy.md`.

### 5 · Datos clínicos

Ninguno, por política. En concreto: solo fixtures sintéticos, ninguna ruta de importación
DICOM, y etiqueta visible de prototipo/no-clínico tanto en la UI como en el nombre de los
nodos.

Se mantiene la regla ya escrita en `docs/slicer/slicer_module_architecture.md`: *"Logic
should not depend on the widget"*.

---

## 11. Pruebas automatizables con imágenes sintéticas

Casi todo es testeable **sin socket alguno**, que es el punto clave.

### Fixture base

Extensión de `SLIAFlowTest._createSyntheticVolume()`:

```python
@staticmethod
def _createSyntheticRgbVolume(name="SyntheticRGB", width=64, height=48):
    volumeNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLVectorVolumeNode", name)
    imageData = vtk.vtkImageData()
    imageData.SetDimensions(width, height, 1)
    imageData.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 3)
    volumeNode.SetAndObserveImageData(imageData)
    return volumeNode
```

### Suite de validación (rápida, headless, sin red)

Acepta 3 componentes `uint8`; rechaza 1 componente; rechaza imagen vacía o
`GetImageData() is None`; rechaza dtype inesperado; rechaza dimensiones incoherentes con
la entrada; rechaza `None`. Cada caso debe además verificar que la escena no se modificó.

### Suite de detección (§9, sin red)

Crear un vector volume, registrar el observador de la logic, mutar el array y llamar a
`slicer.util.arrayFromVolumeModified(node)`, y afirmar que el callback se disparó
exactamente una vez y que el contador de resultados avanzó. Esto ejercita el mecanismo
real de recepción sin un solo byte de socket.

### Persistencia

Extender `test_parameterNode_persistsInputVolumeAcrossSceneLoad` a un vector volume;
mismo patrón de `saveScene`/`Clear`/`loadScene` ya escrito.

### Presentación

A nivel MRML (IDs correctos en los composite nodes correctos), con la cautela de
`--no-main-window` de la sección 10.

### Integración loopback (opcional, más adelante, fuera del test por defecto)

`pyigtl` (PyPI, recomendado por el core dev de Slicer Kyle Sunderland en
`discourse.slicer.org` id36194) permite levantar un servidor IGTL en un hilo y enviar un
`ImageMessage` RGB sintético a `127.0.0.1`. Debe ser *skippable* con
`hasattr(slicer, "vtkMRMLIGTLConnectorNode")` para no romper el runner cuando la
extensión no está. El patrón de referencia en C++ es
`OpenIGTLinkIF/Testing/vtkMRMLConnectorImageSendAndReceiveTest.cxx`.

---

## 12. Nueva secuencia de tareas STRATUM propuesta

Manteniendo el ciclo de vida de `AGENTS.md` y la plantilla `.ai/templates/task-template.md`.
Cada tarea es pequeña, revisable y deja un artefacto que sobrevive a la siguiente.

| ID | Título | Entregable | Depende |
|---|---|---|---|
| **STR-001** | Fijar el runtime Slicer objetivo | Decidir oficial 5.13.0 vs `apps/SR`; verificar disponibilidad de SlicerOpenIGTLink para esa revisión; actualizar `config/local.example.json` y `docs/slicer/openigtlink_environment.md` | — |
| **STR-002** | ADR del contrato de cable | Primer ADR en `docs/architecture/decisions/`: IMAGE sobre OpenIGTLink, Slicer=servidor:18944, device names `STRATUM_INPUT`/`STRATUM_UC2`, RGB uint8, algoritmo fuera de proceso | STR-001 |
| **STR-003** | MVP manual, cero código en SLIAFlow | Emisor sintético con `pyigtl` + `docs/slicer/igtl_reception_walkthrough.md` con evidencia de los dos `vtkMRMLVectorVolumeNode` | STR-002 |
| **STR-004** | Capa de validación | `SLIAFlowValidation.py`; añadir `GetNumberOfScalarComponents()` a `inspectVolumeMetadata`; suite sintética completa | STR-002 |
| **STR-005** | Detección de resultados | Observadores `ImageDataModifiedEvent` + `NodeAddedEvent` en la Logic, sin importar clases IGTL; `resultVolumeNode` en el parameter node | STR-004 |
| **STR-006** | Presentación lado a lado | `SLIAFlowPresentation.py`: layout personalizado, asignación por vista, etiquetado no-clínico | STR-005 |
| **STR-007** | Panel STRATUM en la UI | Sección colapsable nueva en el `.ui`, reutilizando `_setSummaryState` y el patrón de parameter node | STR-006 |
| **STR-008** | Test de integración loopback (opcional) | Test `pyigtl` skippable, fuera del runner por defecto | STR-003, STR-005 |
| **STR-009** | Persistencia y provenance | BSSL-008 reformulado sobre resultados reales | STR-007 |

### Cierre del backlog anterior

- BSSL-006 queda superada por STR-002 + STR-004.
- BSSL-007 queda superada por STR-005 + STR-006 + STR-007.
- BSSL-008 se convierte en STR-009.

### Sobre el orden

STR-001 va primero porque es la única tarea que puede invalidar a todas las demás: si la
extensión no está disponible para el build objetivo, el plan cambia de forma. Y STR-003
(el MVP manual) va deliberadamente antes que cualquier código, porque da evidencia real
de la forma exacta de los datos de UC2 antes de escribir la validación que los juzga.

---

## Riesgo abierto principal

La disponibilidad de SlicerOpenIGTLink para 3D Slicer 5.13.0 build 2026-07-02. No se ha
podido verificar durante este análisis: requiere consultar el Extension Manager en la
instalación local. Es lo primero que conviene comprobar, antes de escribir ninguna tarea.

---

## Referencias

### Repositorio

- `extensions/SLIAFlow/SLIAFlow/SLIAFlow.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowLogic.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowWidget.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowParameterNode.py`
- `extensions/SLIAFlow/SLIAFlow/SLIAFlowLib/SLIAFlowTest.py`
- `extensions/SLIAFlow/SLIAFlow/Resources/UI/SLIAFlow.ui`
- `extensions/SLIAFlow/SLIAFlow/Testing/Python/SLIAFlowModuleTest.py`
- `scripts/development/run-slicer-tests.ps1`
- `.ai/policies/algorithm-boundary-policy.md`
- `.ai/policies/medical-data-policy.md`
- `docs/slicer/slicer_module_architecture.md`
- `docs/development/testing_strategy.md`

### Slicer y extensiones (fuera del repositorio)

- `Libs/MRML/Core/vtkMRMLVolumeNode.h` — `ImageDataModifiedEvent`, `SetAndObserveImageData`
- `Libs/MRML/Core/vtkMRMLLayoutNode.h` — constantes de layout
- `Libs/MRML/Core/vtkMRMLSliceNode.h` — `RotateToVolumePlane`
- `Libs/MRML/Core/vtkMRMLSliceCompositeNode.h` — `SetLinkedControl`
- `Libs/MRML/Logic/vtkMRMLSliceLogic.h` — `FitSliceToAll`
- `Base/Python/slicer/util.py` — `setSliceViewerLayers`
- `Docs/developer_guide/script_repository/gui.md` — layouts personalizados
- `Docs/developer_guide/script_repository/volumes.md` — composite nodes
- SlicerOpenIGTLink: `OpenIGTLinkIF/MRML/vtkMRMLIGTLConnectorNode.h` y `.cxx`
- SlicerOpenIGTLink: `OpenIGTLinkIF/Testing/vtkMRMLConnectorImageSendAndReceiveTest.cxx`
- aigt: `HerniaRepairTutor/RecordHerniaData/RecordHerniaData.py`
- SlicerIGT: `Guidelet/GuideletLib/Guidelet.py`
- pyigtl: https://pypi.org/project/pyigtl/
