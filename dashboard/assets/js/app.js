const API = "/api";

// ─── Configuracion del zoom de la grafica (ajustar aqui si hace falta) ─────
const MS_HORA = 60 * 60 * 1000;
const MS_DIA = 24 * MS_HORA;
const MS_MES = 30 * MS_DIA; // aproximado, solo para acotar la ventana por defecto

const CONFIG_ZOOM = {
    // ventanaInicial: cuanto se ve al entrar o cambiar de agrupacion/servidor.
    // minVentana: que tan cerca se puede hacer zoom in con la rueda del mouse.
    // pasoScroll: cuanto cambia la ventana por cada "tick" de la rueda.
    hora: { ventanaInicial: 2 * MS_DIA, minVentana: 12 * MS_HORA, pasoScroll: 6 * MS_HORA },
    dia: { ventanaInicial: 7 * MS_DIA, minVentana: 2 * MS_DIA, pasoScroll: 1 * MS_DIA },
    mes: { ventanaInicial: 4 * MS_MES, minVentana: 1 * MS_MES, pasoScroll: 1 * MS_MES },
};

const estado = {
    servidor: null,
    agrupacion: "hora",
    filasHistorico: null,  // filas crudas de la API, para poder recolorear sin re-pedirlas (cambio de tema)
    seriesCompletas: null, // series ya construidas, SIN recortar a la ventana visible
    rangoDatos: null,      // {inicio, fin} en ms: todo el historico disponible para servidor+agrupacion actuales
    ventanaMs: null,       // ancho de la ventana visible actual, en ms
    finVentana: null,      // extremo derecho (mas reciente) de la ventana visible, en ms
};

// ─── Tema (claro/oscuro) ───────────────────────────────────────────────────
function aplicarTema(tema) {
    document.documentElement.setAttribute("data-theme", tema === "claro" ? "claro" : "oscuro");
    document.getElementById("logo").src =
        tema === "claro" ? "assets/img/logo-horizontal-marino.png" : "assets/img/logo-horizontal-naranja.png";
    document.getElementById("icono-tema").src =
        tema === "claro" ? "assets/img/tema-claro.png" : "assets/img/tema-oscuro.png";
}

function initTema() {
    let guardado = "oscuro";
    try {
        guardado = localStorage.getItem("tema") || "oscuro";
    } catch (e) { /* localStorage no disponible (ventana privada, etc.) */ }

    aplicarTema(guardado);

    document.getElementById("boton-tema").addEventListener("click", () => {
        const actual = document.documentElement.getAttribute("data-theme") === "claro" ? "claro" : "oscuro";
        const nuevo = actual === "claro" ? "oscuro" : "claro";
        aplicarTema(nuevo);
        try { localStorage.setItem("tema", nuevo); } catch (e) { /* ignorar */ }
        // Recalcula colores de serie segun el tema nuevo, sin perder el zoom/desplazamiento actual.
        if (estado.filasHistorico) {
            estado.seriesCompletas = construirSeries(estado.filasHistorico);
            actualizarVista();
        }
    });
}

// ─── Utilidades ─────────────────────────────────────────────────────────────
function cssVar(nombre) {
    return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
}

function formatearFecha(iso, agrupacion) {
    const d = new Date(iso);
    if (agrupacion === "hora") return d.toLocaleString("es-MX", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    if (agrupacion === "dia") return d.toLocaleString("es-MX", { day: "2-digit", month: "short" });
    return d.toLocaleString("es-MX", { month: "short", year: "numeric" });
}

async function obtenerJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`);
    return resp.json();
}

// ─── Arbol de servidores (sidebar) ──────────────────────────────────────────
function renderNodoArbol(nodo) {
    if (nodo.tipo === "servidor") {
        return `<li class="arbol-servidor" data-nombre="${nodo.nombre}" data-activo="${nodo.activo}">${nodo.nombre}</li>`;
    }
    const hijosHtml = nodo.hijos.map(renderNodoArbol).join("");
    return `
        <li class="arbol-grupo">
            <div class="arbol-etiqueta">${nodo.nombre}</div>
            <ul>${hijosHtml}</ul>
        </li>
    `;
}

// Primer servidor que encuentre, recorriendo el arbol a profundidad (para la seleccion inicial).
function primerServidor(nodos) {
    for (const nodo of nodos) {
        if (nodo.tipo === "servidor") return nodo.nombre;
        const encontrado = primerServidor(nodo.hijos);
        if (encontrado) return encontrado;
    }
    return null;
}

function seleccionarServidor(nombre) {
    estado.servidor = nombre;
    document.querySelectorAll(".arbol-servidor.seleccionado").forEach(el => el.classList.remove("seleccionado"));
    document.querySelector(`.arbol-servidor[data-nombre="${CSS.escape(nombre)}"]`)?.classList.add("seleccionado");
    cargarActual();
    cargarHistorico();
}

// Pinta el arbol. Se llama tanto al cargar la pagina como al presionar
// "Actualizar" -- NO reengancha el clic (eso se hace una sola vez, ver
// initArbolClicks) y NO salta a reseleccionar el primer servidor si ya
// habia uno elegido, solo lo remarca visualmente despues de repintar.
async function cargarArbol() {
    const contenedor = document.getElementById("arbol-servidores");
    try {
        const arbol = await obtenerJSON(`${API}/grupos`);

        if (arbol.length === 0) {
            contenedor.innerHTML = `<p class="mensaje-vacio">Sin servidores todavía.</p>`;
            return;
        }

        contenedor.innerHTML = `<ul>${arbol.map(renderNodoArbol).join("")}</ul>`;

        if (estado.servidor) {
            document.querySelector(`.arbol-servidor[data-nombre="${CSS.escape(estado.servidor)}"]`)?.classList.add("seleccionado");
        } else {
            const inicial = primerServidor(arbol);
            if (inicial) seleccionarServidor(inicial);
        }
    } catch (e) {
        contenedor.innerHTML = `<p class="mensaje-vacio">Error al cargar servidores.</p>`;
        console.error(e);
    }
}

// Delegacion de clic sobre el arbol -- se engancha UNA sola vez (el contenedor
// nunca se reemplaza, solo su innerHTML en cargarArbol, asi que la delegacion
// sigue funcionando sobre el contenido nuevo sin volver a engancharse).
function initArbolClicks() {
    document.getElementById("arbol-servidores").addEventListener("click", (ev) => {
        const etiqueta = ev.target.closest(".arbol-etiqueta");
        if (etiqueta) {
            etiqueta.parentElement.classList.toggle("colapsado");
            return;
        }
        const servidor = ev.target.closest(".arbol-servidor");
        if (servidor) {
            seleccionarServidor(servidor.dataset.nombre);
        }
    });
}

// Semaforo de 3 puntos fijos (verde/ambar/rojo) para la columna "Estado" de
// la tabla de sensores -- sin texto, solo se "enciende" el que corresponde.
function renderSemaforo(estadoActual) {
    const colores = ["verde", "ambar", "rojo"];
    return `
        <span class="semaforo">
            ${colores.map(c => `<span class="semaforo__punto" data-color="${c}" data-activo="${c === estadoActual}"></span>`).join("")}
        </span>
    `;
}

// ─── Estado actual (tarjetas + tabla) ──────────────────────────────────────
async function cargarActual() {
    if (!estado.servidor) return;
    const contenedorTarjetas = document.getElementById("tarjetas");
    const cuerpoTabla = document.getElementById("tabla-sensores");

    try {
        const [lecturas, hardware] = await Promise.all([
            obtenerJSON(`${API}/servidores/${encodeURIComponent(estado.servidor)}/actual`),
            obtenerJSON(`${API}/servidores/${encodeURIComponent(estado.servidor)}/hardware`),
        ]);

        if (lecturas.length === 0) {
            contenedorTarjetas.innerHTML = `<p class="mensaje-vacio">Sin lecturas todavía para este servidor.</p>`;
            cuerpoTabla.innerHTML = "";
            return;
        }

        // Tarjeta de CPU: se muestra el core mas caliente (peor caso), no el promedio.
        const cpu = lecturas.filter(l => l.componente === "cpu");
        const gpus = lecturas.filter(l => l.componente === "gpu").sort((a, b) => a.sensor.localeCompare(b.sensor));

        // Subtitulo: modelo de hardware + nucleos si estan en hardware.yaml,
        // si no cae de vuelta al nombre crudo del sensor (comportamiento de siempre).
        const subtituloCpu = hardware.cpu_modelo
            ? `${hardware.cpu_modelo}${hardware.cpu_nucleos ? ` (${hardware.cpu_nucleos} cores)` : ""}`
            : null;
        const subtituloGpu = hardware.gpu_modelo
            ? `${hardware.gpu_modelo}${hardware.gpu_nucleos ? ` (${hardware.gpu_nucleos} cores)` : ""}`
            : null;

        // Mismo orden/paleta que la grafica (construirSeries): CPU siempre
        // --serie-1, GPUs en orden alfabetico sobre --serie-2/--serie-3/--serie-1,
        // asi la franja de color de la tarjeta coincide con la linea de la grafica.
        const coloresGpu = ["--serie-2", "--serie-3", "--serie-1"];

        const tarjetas = [];
        if (cpu.length > 0) {
            const peor = cpu.reduce((max, l) => (l.temperatura_c > max.temperatura_c ? l : max), cpu[0]);
            tarjetas.push({ titulo: "CPU (máx.)", ...peor, sensor: subtituloCpu || peor.sensor, color: cssVar("--serie-1") });
        }
        gpus.forEach((g, i) => {
            tarjetas.push({ titulo: g.sensor.replace("_", " "), ...g, sensor: subtituloGpu || g.sensor, color: cssVar(coloresGpu[i % coloresGpu.length]) });
        });

        contenedorTarjetas.innerHTML = tarjetas.map(t => `
            <div class="tarjeta">
                <div class="tarjeta__titulo">${t.titulo}</div>
                <div class="tarjeta__valor">
                    <span class="punto-estado" data-estado="${t.estado || ''}"></span>${t.temperatura_c}<span class="tarjeta__unidad">°C</span>
                </div>
                <div class="tarjeta__sensor">${t.sensor}</div>
                <div class="tarjeta__franja" style="background-color:${t.color}"></div>
            </div>
        `).join("");

        cuerpoTabla.innerHTML = lecturas.map(l => `
            <tr>
                <td>${l.componente}</td>
                <td>${l.sensor}</td>
                <td>${l.temperatura_c} °C</td>
                <td>${renderSemaforo(l.estado)}</td>
                <td>${new Date(l.medido_en).toLocaleString("es-MX")}</td>
            </tr>
        `).join("");
    } catch (e) {
        contenedorTarjetas.innerHTML = `<p class="mensaje-vacio">Error al cargar el estado actual.</p>`;
        console.error(e);
    }
}

// ─── Historico (grafica) ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("#chips-agrupacion .chip").forEach(boton => {
        boton.addEventListener("click", () => {
            document.querySelectorAll("#chips-agrupacion .chip").forEach(b => b.setAttribute("aria-pressed", "false"));
            boton.setAttribute("aria-pressed", "true");
            estado.agrupacion = boton.dataset.agrupacion;
            cargarHistorico();
        });
    });
});

async function cargarHistorico() {
    if (!estado.servidor) return;
    const svg = document.getElementById("grafica");

    try {
        const filas = await obtenerJSON(
            `${API}/servidores/${encodeURIComponent(estado.servidor)}/historico?agrupacion=${estado.agrupacion}`
        );

        document.querySelector(".grafica-contenedor .mensaje-vacio")?.remove();

        if (filas.length === 0) {
            svg.innerHTML = "";
            document.getElementById("leyenda").innerHTML = "";
            document.getElementById("rango-actual").textContent = "";
            document.getElementById("desplazador").style.display = "none";
            document.querySelector(".grafica-contenedor").insertAdjacentHTML(
                "beforeend", `<p class="mensaje-vacio">Sin histórico todavía para este servidor.</p>`
            );
            return;
        }

        estado.filasHistorico = filas;
        estado.seriesCompletas = construirSeries(filas);

        const todosMs = estado.seriesCompletas.flatMap(s => s.puntos.map(p => new Date(p.periodo).getTime()));
        estado.rangoDatos = { inicio: Math.min(...todosMs), fin: Math.max(...todosMs) };

        const config = CONFIG_ZOOM[estado.agrupacion];
        const rangoTotal = estado.rangoDatos.fin - estado.rangoDatos.inicio;
        estado.ventanaMs = rangoTotal > 0 ? Math.min(config.ventanaInicial, rangoTotal) : config.ventanaInicial;
        estado.finVentana = estado.rangoDatos.fin;

        actualizarVista();
    } catch (e) {
        svg.innerHTML = "";
        console.error(e);
    }
}

// Para el refresco automatico: vuelve a pedir el historico pero preserva el
// zoom/desplazamiento del usuario (si estaba viendo el borde mas reciente, se
// mueve con el; si se habia desplazado a un periodo viejo, se queda ahi).
async function refrescarHistorico() {
    if (!estado.servidor || !estado.rangoDatos) return;
    try {
        const filas = await obtenerJSON(
            `${API}/servidores/${encodeURIComponent(estado.servidor)}/historico?agrupacion=${estado.agrupacion}`
        );
        if (filas.length === 0) return;

        const seguiaElFinal = estado.finVentana === estado.rangoDatos.fin;

        estado.filasHistorico = filas;
        estado.seriesCompletas = construirSeries(filas);
        const todosMs = estado.seriesCompletas.flatMap(s => s.puntos.map(p => new Date(p.periodo).getTime()));
        estado.rangoDatos = { inicio: Math.min(...todosMs), fin: Math.max(...todosMs) };
        estado.finVentana = Math.min(seguiaElFinal ? estado.rangoDatos.fin : estado.finVentana, estado.rangoDatos.fin);

        actualizarVista();
    } catch (e) {
        console.error(e);
    }
}

// Redibuja grafica + leyenda + rango + desplazador a partir del estado actual
// de zoom/desplazamiento (estado.ventanaMs / estado.finVentana), sin volver a
// pedirle nada al backend -- ya se tiene todo el historico en memoria.
function actualizarVista() {
    const inicioVentana = estado.finVentana - estado.ventanaMs;

    const seriesRecortadas = estado.seriesCompletas.map(s => ({
        ...s,
        puntos: s.puntos.filter(p => {
            const t = new Date(p.periodo).getTime();
            return t >= inicioVentana && t <= estado.finVentana;
        }),
    }));

    renderGrafica(document.getElementById("grafica"), seriesRecortadas, estado.agrupacion);
    renderLeyenda(document.getElementById("leyenda"), estado.seriesCompletas);
    renderRangoActual(inicioVentana, estado.finVentana);
    renderDesplazador(inicioVentana);
}

function renderRangoActual(inicioMs, finMs) {
    const fmt = (ms) => new Date(ms).toLocaleDateString("es-MX", { day: "2-digit", month: "short", year: "numeric" });
    document.getElementById("rango-actual").textContent = `${fmt(inicioMs)} – ${fmt(finMs)}`;
}

function renderDesplazador(inicioVentana) {
    const desplazador = document.getElementById("desplazador");
    const miniatura = document.getElementById("desplazador-miniatura");
    const { inicio, fin } = estado.rangoDatos;
    const rangoTotal = fin - inicio;

    if (rangoTotal <= 0 || estado.ventanaMs >= rangoTotal) {
        desplazador.style.display = "none";
        return;
    }

    const porcentajeAncho = Math.max(4, (estado.ventanaMs / rangoTotal) * 100);
    const porcentajeInicio = ((inicioVentana - inicio) / rangoTotal) * 100;

    desplazador.style.display = "block";
    miniatura.style.width = `${porcentajeAncho}%`;
    miniatura.style.left = `${Math.max(0, Math.min(100 - porcentajeAncho, porcentajeInicio))}%`;
}

// ─── Zoom con scroll (rueda arriba = acercar, abajo = alejar) ──────────────
function manejarZoomScroll(ev) {
    if (!estado.rangoDatos) return;
    ev.preventDefault();

    const config = CONFIG_ZOOM[estado.agrupacion];
    const rangoTotal = estado.rangoDatos.fin - estado.rangoDatos.inicio;
    const direccion = ev.deltaY < 0 ? -1 : 1;

    const nuevaVentana = Math.max(config.minVentana, Math.min(rangoTotal, estado.ventanaMs + direccion * config.pasoScroll));
    estado.ventanaMs = nuevaVentana;

    if (estado.finVentana - estado.ventanaMs < estado.rangoDatos.inicio) {
        estado.finVentana = estado.rangoDatos.inicio + estado.ventanaMs;
    }
    if (estado.finVentana > estado.rangoDatos.fin) {
        estado.finVentana = estado.rangoDatos.fin;
    }

    actualizarVista();
}

// ─── Desplazador horizontal (arrastrar para ver periodos anteriores) ──────
function initDesplazador() {
    const desplazador = document.getElementById("desplazador");
    const miniatura = document.getElementById("desplazador-miniatura");
    let arrastrando = false;
    let inicioArrastreX = 0;
    let inicioVentanaAlArrastrar = 0;

    const mover = (clientX) => {
        const rangoTotal = estado.rangoDatos.fin - estado.rangoDatos.inicio;
        const deltaMs = ((clientX - inicioArrastreX) / desplazador.clientWidth) * rangoTotal;
        let nuevoInicio = inicioVentanaAlArrastrar + deltaMs;
        nuevoInicio = Math.max(estado.rangoDatos.inicio, Math.min(estado.rangoDatos.fin - estado.ventanaMs, nuevoInicio));
        estado.finVentana = nuevoInicio + estado.ventanaMs;
        actualizarVista();
    };

    miniatura.addEventListener("pointerdown", (ev) => {
        arrastrando = true;
        miniatura.classList.add("arrastrando");
        inicioArrastreX = ev.clientX;
        inicioVentanaAlArrastrar = estado.finVentana - estado.ventanaMs;
        miniatura.setPointerCapture(ev.pointerId);
    });
    miniatura.addEventListener("pointermove", (ev) => { if (arrastrando) mover(ev.clientX); });
    const terminarArrastre = () => { arrastrando = false; miniatura.classList.remove("arrastrando"); };
    miniatura.addEventListener("pointerup", terminarArrastre);
    miniatura.addEventListener("pointercancel", terminarArrastre);

    // Clic en la pista (fuera de la miniatura): salta la ventana a ese punto.
    desplazador.addEventListener("click", (ev) => {
        if (ev.target === miniatura || !estado.rangoDatos) return;
        const rect = desplazador.getBoundingClientRect();
        const fraccion = (ev.clientX - rect.left) / rect.width;
        const rangoTotal = estado.rangoDatos.fin - estado.rangoDatos.inicio;
        let nuevoInicio = estado.rangoDatos.inicio + fraccion * rangoTotal - estado.ventanaMs / 2;
        nuevoInicio = Math.max(estado.rangoDatos.inicio, Math.min(estado.rangoDatos.fin - estado.ventanaMs, nuevoInicio));
        estado.finVentana = nuevoInicio + estado.ventanaMs;
        actualizarVista();
    });
}

// CPU: promedio de todos los sensores cpu por periodo (una sola linea).
// GPU: una linea por sensor, tal cual la entrega el backend.
function construirSeries(filas) {
    const periodos = new Set();
    const cpuPorPeriodo = new Map();
    const gpuPorSensorYPeriodo = new Map();

    for (const f of filas) {
        periodos.add(f.periodo);
        if (f.componente === "cpu") {
            if (!cpuPorPeriodo.has(f.periodo)) cpuPorPeriodo.set(f.periodo, []);
            cpuPorPeriodo.get(f.periodo).push(Number(f.temperatura_promedio));
        } else {
            if (!gpuPorSensorYPeriodo.has(f.sensor)) gpuPorSensorYPeriodo.set(f.sensor, new Map());
            gpuPorSensorYPeriodo.get(f.sensor).set(f.periodo, Number(f.temperatura_promedio));
        }
    }

    const periodosOrdenados = [...periodos].sort();
    const series = [];
    const coloresGpu = ["--serie-2", "--serie-3", "--serie-1"];

    if (cpuPorPeriodo.size > 0) {
        series.push({
            nombre: "CPU (promedio)",
            color: cssVar("--serie-1"),
            puntos: periodosOrdenados
                .filter(p => cpuPorPeriodo.has(p))
                .map(p => {
                    const valores = cpuPorPeriodo.get(p);
                    const prom = valores.reduce((a, b) => a + b, 0) / valores.length;
                    return { periodo: p, valor: Math.round(prom * 10) / 10 };
                }),
        });
    }

    let i = 0;
    for (const [sensor, mapa] of [...gpuPorSensorYPeriodo.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
        series.push({
            nombre: sensor.replace("_", " "),
            color: cssVar(coloresGpu[i % coloresGpu.length]),
            puntos: periodosOrdenados.filter(p => mapa.has(p)).map(p => ({ periodo: p, valor: mapa.get(p) })),
        });
        i++;
    }

    return series;
}

function renderLeyenda(contenedor, series) {
    contenedor.innerHTML = series.map(s => `
        <div class="leyenda__item">
            <span class="leyenda__muestra" style="background-color:${s.color}"></span>${s.nombre}
        </div>
    `).join("");
}

function renderGrafica(svg, series, agrupacion) {
    const ancho = svg.clientWidth || 1000;
    const alto = 320;
    const margen = { arriba: 16, abajo: 32, izquierda: 44, derecha: 16 };
    const anchoUtil = ancho - margen.izquierda - margen.derecha;
    const altoUtil = alto - margen.arriba - margen.abajo;

    const todosPuntos = series.flatMap(s => s.puntos);
    const periodosUnicos = [...new Set(todosPuntos.map(p => p.periodo))].sort();
    const valores = todosPuntos.map(p => p.valor);
    let yMin = Math.floor(Math.min(...valores) - 2);
    let yMax = Math.ceil(Math.max(...valores) + 2);
    if (yMin === yMax) { yMin -= 5; yMax += 5; }

    const x = (periodo) => {
        const idx = periodosUnicos.indexOf(periodo);
        return margen.izquierda + (periodosUnicos.length <= 1 ? anchoUtil / 2 : (idx / (periodosUnicos.length - 1)) * anchoUtil);
    };
    const y = (valor) => margen.arriba + altoUtil - ((valor - yMin) / (yMax - yMin)) * altoUtil;

    const colorBorde = cssVar("--borde");
    const colorMuted = cssVar("--texto-secundario");

    let svgContenido = "";

    // Gridlines horizontales + etiquetas de eje Y
    const pasosY = 4;
    for (let i = 0; i <= pasosY; i++) {
        const valor = yMin + ((yMax - yMin) / pasosY) * i;
        const yPix = y(valor);
        svgContenido += `<line x1="${margen.izquierda}" y1="${yPix}" x2="${ancho - margen.derecha}" y2="${yPix}" stroke="${colorBorde}" stroke-width="1" />`;
        svgContenido += `<text x="${margen.izquierda - 8}" y="${yPix + 4}" text-anchor="end" font-size="11" fill="${colorMuted}">${Math.round(valor)}°</text>`;
    }

    // Etiquetas de eje X (hasta 6, distribuidas)
    const maxEtiquetas = 6;
    const paso = Math.max(1, Math.ceil(periodosUnicos.length / maxEtiquetas));
    periodosUnicos.forEach((p, idx) => {
        if (idx % paso !== 0 && idx !== periodosUnicos.length - 1) return;
        svgContenido += `<text x="${x(p)}" y="${alto - 8}" text-anchor="middle" font-size="11" fill="${colorMuted}">${formatearFecha(p, agrupacion)}</text>`;
    });

    // Lineas de cada serie
    for (const s of series) {
        if (s.puntos.length === 0) continue;
        const d = s.puntos.map((p, i) => `${i === 0 ? "M" : "L"} ${x(p.periodo)} ${y(p.valor)}`).join(" ");
        svgContenido += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />`;
        for (const p of s.puntos) {
            svgContenido += `<circle cx="${x(p.periodo)}" cy="${y(p.valor)}" r="3" fill="${s.color}" />`;
        }
    }

    svg.setAttribute("viewBox", `0 0 ${ancho} ${alto}`);
    svg.innerHTML = svgContenido;

    activarTooltip(svg, series, periodosUnicos, x, y, margen, anchoUtil, agrupacion);
}

function activarTooltip(svg, series, periodosUnicos, x, y, margen, anchoUtil, agrupacion) {
    let tooltip = document.getElementById("tooltip-grafica");
    if (!tooltip) {
        tooltip = document.createElement("div");
        tooltip.id = "tooltip-grafica";
        tooltip.className = "tooltip-grafica";
        document.querySelector(".grafica-contenedor").style.position = "relative";
        document.querySelector(".grafica-contenedor").appendChild(tooltip);
    }

    svg.onmousemove = (ev) => {
        const rect = svg.getBoundingClientRect();
        const escalaX = svg.viewBox.baseVal.width / rect.width;
        const xPix = (ev.clientX - rect.left) * escalaX;
        const relativo = (xPix - margen.izquierda) / anchoUtil;
        const idx = Math.round(relativo * (periodosUnicos.length - 1));
        if (idx < 0 || idx >= periodosUnicos.length) { tooltip.style.display = "none"; return; }
        const periodo = periodosUnicos[idx];

        const filas = series
            .map(s => ({ nombre: s.nombre, color: s.color, punto: s.puntos.find(p => p.periodo === periodo) }))
            .filter(f => f.punto);

        if (filas.length === 0) { tooltip.style.display = "none"; return; }

        tooltip.innerHTML = `<div style="font-weight:600;margin-bottom:4px">${formatearFecha(periodo, agrupacion)}</div>` +
            filas.map(f => `<div><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${f.color};margin-right:6px"></span>${f.nombre}: ${f.punto.valor}°C</div>`).join("");

        tooltip.style.display = "block";
        tooltip.style.left = `${ev.clientX - rect.left + 12}px`;
        tooltip.style.top = `${ev.clientY - rect.top + 12}px`;
    };
    svg.onmouseleave = () => { tooltip.style.display = "none"; };
}

// ─── Columna reservada (pantallas grandes): mueve "todos los sensores" ahi ──
// En pantallas chicas/normales, #bloque-sensores vive colapsado dentro de
// <main> (su posicion original en el HTML). En pantallas >=1800px, se mueve
// a la columna reservada izquierda y se deja siempre abierto. Reacciona en
// vivo si la ventana cruza el umbral (no solo al cargar la pagina).
function initColumnaReservada() {
    const bloque = document.getElementById("bloque-sensores");
    const reservado = document.getElementById("reservado");
    const hogarOriginal = document.getElementById("seccion-actual");
    const resumen = bloque.querySelector("summary");
    const mq = window.matchMedia("(min-width: 1800px)");

    function mover() {
        if (mq.matches) {
            bloque.open = true;
            resumen.textContent = "Todos los sensores";
            reservado.appendChild(bloque);
        } else {
            bloque.open = false;
            resumen.textContent = "Ver todos los sensores";
            hogarOriginal.appendChild(bloque);
        }
    }

    mq.addEventListener("change", mover);
    mover();
}

// ─── Boton "Actualizar" (dispara la ingesta bajo demanda) ──────────────────
function initBotonActualizar() {
    const boton = document.getElementById("boton-actualizar");
    const textoOriginal = boton.innerHTML;

    boton.addEventListener("click", async () => {
        boton.disabled = true;
        boton.classList.add("cargando");
        boton.innerHTML = `<span class="boton-actualizar__icono">↻</span> Actualizando...`;

        try {
            const resp = await fetch(`${API}/ingesta/ejecutar`, { method: "POST" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const resultado = await resp.json();

            await Promise.all([cargarArbol(), cargarActual(), refrescarHistorico()]);

            const total = resultado.online_cargados + resultado.offline_cargados;
            boton.innerHTML = `<span class="boton-actualizar__icono">✓</span> ${total} archivo(s) nuevos`;
        } catch (e) {
            console.error(e);
            boton.innerHTML = `<span class="boton-actualizar__icono">✕</span> Error al actualizar`;
        } finally {
            boton.classList.remove("cargando");
            setTimeout(() => {
                boton.innerHTML = textoOriginal;
                boton.disabled = false;
            }, 3000);
        }
    });
}

// ─── Inicio ──────────────────────────────────────────────────────────────────
initTema();
initArbolClicks();
cargarArbol();
initDesplazador();
initColumnaReservada();
initBotonActualizar();
document.getElementById("grafica").addEventListener("wheel", manejarZoomScroll, { passive: false });
setInterval(() => { cargarActual(); refrescarHistorico(); }, 5 * 60 * 1000);
