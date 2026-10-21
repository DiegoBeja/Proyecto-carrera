/*
 * Registro de datos PMS5003 + BME688 en ESP32-S3
 * ------------------------------------------------------------------
 * Pines:  SDA = 15, SCL = 16 (BME688)   |   PMS5003 TX -> pin 17 (RX del ESP32)
 * Librerias (Library Manager): "Adafruit BME680 Library" y "Adafruit Unified Sensor"
 * Placa: ESP32S3 Dev Module. Si usan el puerto USB nativo, activen "USB CDC On Boot".
 *
 * Como funciona:
 *  - Los sensores trabajan SIEMPRE con el mismo ciclo (PMS5003 ~1 lectura/s, BME688 cada
 *    BME_PERIOD_MS), con o sin sesion. Asi el BME688 mantiene su ciclo de calentador constante.
 *  - Cada LOG_INTERVAL se guarda UNA fila con el PROMEDIO de todas las lecturas de esa ventana.
 *  - El CSV se escribe en la memoria del ESP32 (LittleFS) fila por fila, y al terminar la
 *    sesion se imprime por serial entre marcas (#BEGIN_CSV / #END_CSV) para que guardar_csv.py
 *    lo guarde en la PC. Tambien se puede pedir despues con el comando "dump".
 *
 * Comandos por Serial Monitor (115200, terminador "Newline"):
 *   help | status | ls
 *   set interval <segundos>     cada cuanto se guarda una fila (2 a 3600)
 *   set duration <minutos>      duracion de la sesion (1 a 1440)
 *   set id <nombre>             identificador de la sesion (ej. C1_ocupacion)
 *   settime AAAA-MM-DD HH:MM:SS fija la hora LOCAL (si no usan WiFi)
 *   start | stop
 *   e <texto>                   anota un evento en la siguiente fila (ej. "e entra persona 3")
 *   dump <archivo> | del <archivo>
 */

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <LittleFS.h>
#include <time.h>
#include <sys/time.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME680.h>

// ======================= PINES =======================
constexpr int PIN_SDA    = 15;
constexpr int PIN_SCL    = 16;
constexpr int PIN_PMS_RX = 18;   // pin del ESP32 conectado al TX del PMS5003

// ================ VALORES POR DEFECTO ================
uint32_t logIntervalS = 10;      // cada cuantos segundos se guarda una fila
uint32_t durationMin  = 2;     // duracion de la sesion en minutos
String   sessionId    = "S01";   // nombre del archivo: /<sessionId>.csv

// BME688: NO cambien esto entre sesiones, y usen lo mismo en el firmware final.
constexpr uint16_t HEATER_TEMP_C  = 320;    // temperatura del calentador (C)
constexpr uint16_t HEATER_MS      = 150;    // duracion del calentamiento (ms)
constexpr uint32_t BME_PERIOD_MS  = 3000;   // una medicion cada 3 s

// WiFi solo para fijar la hora por NTP al arrancar (despues se apaga). Dejen vacio para no usarlo.
const char* WIFI_SSID = "INFINITUM052C";
const char* WIFI_PASS = "4srXAECjed";
const char* TZ_INFO   = "PST8PDT,M3.2.0,M11.1.0";   // hora de Tijuana/Mexicali

constexpr uint32_t SERIAL_BAUD = 115200;

// ===================== ESTADO ========================
Adafruit_BME680 bme;
bool bmeOk      = false;
bool timeSynced = false;

bool     running = false;
File     logFile;
String   logName;
String   activeId;
uint32_t startMs = 0, nextLogMs = 0, nextBmeMs = 0, rowCount = 0;
uint32_t effInterval = 10, effDuration = 120;

// Acumuladores de la ventana actual
double   pmsSum[12]; uint32_t pmsN = 0;   // 0-5: PM (cf1 y atm), 6-11: conteos por tamano
double   bmeSum[4];  uint32_t bmeN = 0;   // temp, HR, presion (hPa), resistencia de gas (ohm)
String   pendingEvent;

// Ultimas lecturas (para "status")
double   lastPms[12]; bool havePms = false;
double   lastBme[4];  bool haveBme = false;

const char* CSV_HEADER =
  "session_id,epoch_utc,timestamp_local,elapsed_s,pms_n,"
  "pm1_0_cf1,pm2_5_cf1,pm10_cf1,pm1_0_atm,pm2_5_atm,pm10_atm,"
  "n0_3,n0_5,n1_0,n2_5,n5_0,n10,"
  "bme_n,temp_c,rh_pct,pressure_hpa,gas_ohm,log10_gas,abs_hum_gm3,"
  "heater_c,heater_ms,event,co2_ref_ppm";

// ================== UTILIDADES =======================
double absHumidity(double tC, double rh) {   // g/m3
  return 6.112 * exp(17.67 * tC / (tC + 243.5)) * rh * 2.1674 / (273.15 + tC);
}

void resetAccumulators() {
  for (int i = 0; i < 12; i++) pmsSum[i] = 0;
  for (int i = 0; i < 4; i++)  bmeSum[i] = 0;
  pmsN = 0; bmeN = 0;
}

String sanitizeId(String s) {
  String o;
  for (size_t i = 0; i < s.length() && o.length() < 40; i++) {
    char c = s[i];
    if (isalnum((unsigned char)c) || c == '_' || c == '-') o += c;
  }
  return o;
}

String sanitizeEvent(String s) {
  s.replace(",", ";");
  s.replace("\n", " ");
  s.replace("\r", " ");
  return s;
}

String normPath(String n) {
  n.trim();
  if (!n.startsWith("/")) n = "/" + n;
  return n;
}

bool syncTime() {
  if (strlen(WIFI_SSID) == 0) return false;
  Serial.print("Conectando a WiFi para fijar la hora");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) { delay(300); Serial.print("."); }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("No se pudo conectar. Usen 'settime' para fijar la hora.");
    WiFi.mode(WIFI_OFF);
    return false;
  }
  configTzTime(TZ_INFO, "pool.ntp.org", "time.google.com");
  struct tm ti;
  bool ok = getLocalTime(&ti, 10000);
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);   // se apaga para no calentar el BME688
  Serial.println(ok ? "Hora sincronizada por NTP." : "NTP fallo. Usen 'settime'.");
  return ok;
}

String localTimeString() {
  if (!timeSynced) return "sin hora";
  time_t now = time(nullptr);
  struct tm t; localtime_r(&now, &t);
  char b[24]; strftime(b, sizeof b, "%Y-%m-%d %H:%M:%S", &t);
  return String(b);
}

// ================== LECTURA PMS5003 ==================
// Trama de 32 bytes: 0x42 0x4D, longitud (28), 13 palabras de datos, suma de verificacion.
void pmsService() {
  static uint8_t buf[32];
  static uint8_t idx = 0;
  while (Serial1.available()) {
    uint8_t b = Serial1.read();
    if (idx == 0) {
      if (b == 0x42) buf[idx++] = b;
    } else if (idx == 1) {
      if (b == 0x4D) buf[idx++] = b;
      else idx = (b == 0x42) ? 1 : 0;
    } else {
      buf[idx++] = b;
      if (idx == 32) {
        idx = 0;
        uint16_t sum = 0;
        for (int i = 0; i < 30; i++) sum += buf[i];
        uint16_t chk = ((uint16_t)buf[30] << 8) | buf[31];
        uint16_t len = ((uint16_t)buf[2] << 8) | buf[3];
        if (sum == chk && len == 28) {
          for (int i = 0; i < 12; i++) {
            double v = ((uint16_t)buf[4 + 2 * i] << 8) | buf[5 + 2 * i];
            lastPms[i] = v;
            if (running) pmsSum[i] += v;
          }
          havePms = true;
          if (running) pmsN++;
        }
      }
    }
  }
}

// ================== LECTURA BME688 ===================
void bmeService() {
  if (!bmeOk) return;
  uint32_t now = millis();
  if ((int32_t)(now - nextBmeMs) < 0) return;
  nextBmeMs += BME_PERIOD_MS;
  if ((int32_t)(now - nextBmeMs) > 0) nextBmeMs = now + BME_PERIOD_MS;   // si nos atrasamos, no recuperar
  if (!bme.performReading()) return;
  double v[4] = { bme.temperature, bme.humidity, bme.pressure / 100.0, bme.gas_resistance };
  for (int i = 0; i < 4; i++) {
    lastBme[i] = v[i];
    if (running) bmeSum[i] += v[i];
  }
  haveBme = true;
  if (running) bmeN++;
}

// ================== FILA DEL CSV =====================
String buildRow(uint32_t elapsedS) {
  String r; r.reserve(320);
  r += activeId;
  if (timeSynced) {
    time_t now = time(nullptr);
    struct tm t; localtime_r(&now, &t);
    char tb[24]; strftime(tb, sizeof tb, "%Y-%m-%d %H:%M:%S", &t);
    r += ','; r += String((unsigned long)now);
    r += ','; r += tb;
  } else {
    r += ",,";
  }
  r += ','; r += String((unsigned long)elapsedS);
  r += ','; r += String((unsigned long)pmsN);
  for (int i = 0; i < 12; i++) {
    r += ',';
    if (pmsN) r += String(pmsSum[i] / pmsN, 1);
  }
  r += ','; r += String((unsigned long)bmeN);
  if (bmeN) {
    double t = bmeSum[0] / bmeN, h = bmeSum[1] / bmeN, p = bmeSum[2] / bmeN, g = bmeSum[3] / bmeN;
    r += ','; r += String(t, 2);
    r += ','; r += String(h, 2);
    r += ','; r += String(p, 2);
    r += ','; r += String(g, 0);
    r += ','; r += String(log10(g), 4);
    r += ','; r += String(absHumidity(t, h), 3);
  } else {
    r += ",,,,,,";
  }
  r += ','; r += String((int)HEATER_TEMP_C);
  r += ','; r += String((int)HEATER_MS);
  r += ','; r += pendingEvent;
  r += ',';                       // co2_ref_ppm: se llena despues con los datos del AQM65
  return r;
}

// ================== ARCHIVOS =========================
void dumpFile(String name) {
  name = normPath(name);
  File f = LittleFS.open(name, "r");
  if (!f) { Serial.println("No existe: " + name); return; }
  Serial.print("#BEGIN_CSV,"); Serial.println(name.substring(1));
  uint8_t b[256]; size_t n;
  while ((n = f.read(b, sizeof b)) > 0) Serial.write(b, n);
  f.close();
  Serial.println("#END_CSV");
  Serial.flush();
}

void listFiles() {
  File root = LittleFS.open("/");
  File f = root.openNextFile();
  while (f) {
    Serial.printf("  %s  %lu bytes\n", f.name(), (unsigned long)f.size());
    f = root.openNextFile();
  }
  Serial.printf("Libre: %lu KB\n", (unsigned long)((LittleFS.totalBytes() - LittleFS.usedBytes()) / 1024));
}

// ================== SESION ===========================
void startSession() {
  if (running) { Serial.println("Ya hay una sesion en curso."); return; }
  if (!bmeOk) Serial.println("AVISO: BME688 no detectado, esas columnas quedaran vacias.");
  if (!timeSynced) Serial.println("AVISO: sin hora. Anoten la hora de inicio o usen 'settime'.");

  String base = sessionId;
  String name = "/" + base + ".csv";
  int n = 2;
  while (LittleFS.exists(name)) { name = "/" + base + "_" + String(n) + ".csv"; n++; }
  logFile = LittleFS.open(name, "w");
  if (!logFile) { Serial.println("No se pudo crear el archivo."); return; }
  logName  = name;
  activeId = name.substring(1, name.length() - 4);
  logFile.println(CSV_HEADER);
  logFile.flush();

  effInterval = logIntervalS;
  effDuration = durationMin;
  resetAccumulators();
  pendingEvent = "";
  rowCount = 0;
  startMs   = millis();
  nextLogMs = startMs + effInterval * 1000UL;
  running   = true;
  Serial.printf("SESION INICIADA: %s | fila cada %lu s | duracion %lu min | inicio %s\n",
                logName.c_str(), (unsigned long)effInterval, (unsigned long)effDuration,
                localTimeString().c_str());
}

void finishSession(const char* why) {
  running = false;
  logFile.close();
  Serial.printf("SESION TERMINADA (%s): %lu filas en %s | fin %s\n",
                why, (unsigned long)rowCount, logName.c_str(), localTimeString().c_str());
  dumpFile(logName);
}

void printStatus() {
  Serial.println("---- ESTADO ----");
  Serial.printf("Sesion: %s | intervalo %lu s | duracion %lu min | %s\n",
                sessionId.c_str(), (unsigned long)logIntervalS, (unsigned long)durationMin,
                running ? "EN CURSO" : "detenida");
  Serial.printf("Hora: %s\n", localTimeString().c_str());
  if (running) {
    Serial.printf("Transcurrido: %lu s, filas: %lu, archivo: %s\n",
                  (unsigned long)((millis() - startMs) / 1000), (unsigned long)rowCount, logName.c_str());
  }
  if (havePms) Serial.printf("PMS5003: PM1=%.0f PM2.5=%.0f PM10=%.0f (atm, ug/m3)\n", lastPms[3], lastPms[4], lastPms[5]);
  else         Serial.println("PMS5003: sin datos (revisen el cable TX -> pin 17 y la alimentacion de 5 V)");
  if (haveBme) Serial.printf("BME688: T=%.1f C  HR=%.1f %%  P=%.1f hPa  gas=%.0f ohm\n", lastBme[0], lastBme[1], lastBme[2], lastBme[3]);
  else         Serial.println(bmeOk ? "BME688: esperando primera lectura" : "BME688: NO detectado (revisen SDA 15, SCL 16)");
  listFiles();
}

void printHelp() {
  Serial.println("Comandos: help | status | ls | set interval <s> | set duration <min> | set id <nombre>");
  Serial.println("          settime AAAA-MM-DD HH:MM:SS | start | stop | e <evento> | dump <archivo> | del <archivo>");
}

// ================== COMANDOS =========================
void handleLine(String line) {
  line.trim();
  if (!line.length()) return;
  String cmd = line, arg = "";
  int sp = line.indexOf(' ');
  if (sp > 0) { cmd = line.substring(0, sp); arg = line.substring(sp + 1); arg.trim(); }
  cmd.toLowerCase();

  if (cmd == "help") { printHelp(); }
  else if (cmd == "status") { printStatus(); }
  else if (cmd == "ls") { listFiles(); }
  else if (cmd == "start") { startSession(); }
  else if (cmd == "stop") { if (running) finishSession("detenida a mano"); else Serial.println("No hay sesion en curso."); }
  else if (cmd == "dump") { if (running) Serial.println("Esperen a que termine la sesion."); else dumpFile(arg); }
  else if (cmd == "del") {
    if (running) { Serial.println("Esperen a que termine la sesion."); return; }
    String p = normPath(arg);
    Serial.println(LittleFS.remove(p) ? "Borrado " + p : "No existe " + p);
  }
  else if (cmd == "e") {
    if (!running) { Serial.println("Solo se pueden anotar eventos durante una sesion."); return; }
    pendingEvent = sanitizeEvent(arg);
    Serial.println("Evento anotado para la siguiente fila: " + pendingEvent);
  }
  else if (cmd == "settime") {
    if (running) { Serial.println("No cambien la hora durante una sesion."); return; }
    int y, mo, d, h, mi, s;
    if (sscanf(arg.c_str(), "%d-%d-%d %d:%d:%d", &y, &mo, &d, &h, &mi, &s) != 6) {
      Serial.println("Formato: settime 2026-10-14 05:00:00 (hora local)"); return;
    }
    struct tm t = {};
    t.tm_year = y - 1900; t.tm_mon = mo - 1; t.tm_mday = d;
    t.tm_hour = h; t.tm_min = mi; t.tm_sec = s; t.tm_isdst = -1;
    struct timeval tv = { mktime(&t), 0 };
    settimeofday(&tv, nullptr);
    timeSynced = true;
    Serial.println("Hora fijada: " + localTimeString());
  }
  else if (cmd == "set") {
    if (running) { Serial.println("No cambien la configuracion durante una sesion."); return; }
    String key = arg, val = "";
    int sp2 = arg.indexOf(' ');
    if (sp2 > 0) { key = arg.substring(0, sp2); val = arg.substring(sp2 + 1); val.trim(); }
    key.toLowerCase();
    if (key == "interval") {
      long v = val.toInt();
      if (v < 2 || v > 3600) { Serial.println("Intervalo entre 2 y 3600 s."); return; }
      logIntervalS = v;
      Serial.printf("Intervalo: %lu s\n", (unsigned long)logIntervalS);
    } else if (key == "duration") {
      long v = val.toInt();
      if (v < 1 || v > 1440) { Serial.println("Duracion entre 1 y 1440 min."); return; }
      durationMin = v;
      Serial.printf("Duracion: %lu min\n", (unsigned long)durationMin);
    } else if (key == "id") {
      String v = sanitizeId(val);
      if (!v.length()) { Serial.println("Nombre invalido (letras, numeros, _ y -)."); return; }
      sessionId = v;
      Serial.println("Identificador: " + sessionId);
    } else {
      Serial.println("Uso: set interval <s> | set duration <min> | set id <nombre>");
    }
  }
  else { Serial.println("Comando no reconocido. Escriban 'help'."); }
}

void readSerial() {
  static String buf;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) { handleLine(buf); buf = ""; }
    } else if (buf.length() < 120) {
      buf += c;
    }
  }
}

// ================== SETUP / LOOP =====================
void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(1500);
  Serial.println("\n=== Registro PMS5003 + BME688 ===");

  setenv("TZ", TZ_INFO, 1);
  tzset();

  if (!LittleFS.begin(true)) Serial.println("ERROR: no se pudo iniciar LittleFS");

  Serial1.setRxBufferSize(512);
  Serial1.begin(9600, SERIAL_8N1, PIN_PMS_RX, -1);

  Wire.begin(PIN_SDA, PIN_SCL);
  bmeOk = bme.begin(0x77) || bme.begin(0x76);
  if (bmeOk) {
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    bme.setGasHeater(HEATER_TEMP_C, HEATER_MS);
  }
  nextBmeMs = millis();

  timeSynced = syncTime();
  resetAccumulators();
  printHelp();
  printStatus();
}

void loop() {
  readSerial();
  pmsService();
  bmeService();

  if (running && (int32_t)(millis() - nextLogMs) >= 0) {
    uint32_t elapsed = (rowCount + 1) * effInterval;
    String row = buildRow(elapsed);
    logFile.println(row);
    logFile.flush();
    Serial.printf("[%lu/%lu s] fila %lu | PMS n=%lu PM2.5=%.1f | BME n=%lu T=%.1f HR=%.1f gas=%.0f\n",
                  (unsigned long)elapsed, (unsigned long)(effDuration * 60UL), (unsigned long)(rowCount + 1),
                  (unsigned long)pmsN, pmsN ? pmsSum[4] / pmsN : 0.0,
                  (unsigned long)bmeN, bmeN ? bmeSum[0] / bmeN : 0.0,
                  bmeN ? bmeSum[1] / bmeN : 0.0, bmeN ? bmeSum[3] / bmeN : 0.0);
    pendingEvent = "";
    resetAccumulators();
    rowCount++;
    nextLogMs += effInterval * 1000UL;
    if (elapsed + effInterval > effDuration * 60UL) finishSession("tiempo cumplido");
  }
  delay(2);
}
