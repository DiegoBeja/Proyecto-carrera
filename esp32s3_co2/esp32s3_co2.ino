/*
 * Estimacion de CO2 con PMS5003 + BME688 en ESP32-S3 (solo la red; para registrar
 * muestras usen esp32s3_logger).
 * ------------------------------------------------------------------
 * Pines:  SDA = 15, SCL = 16 (BME688)   |   PMS5003 TX -> pin 18 (RX del ESP32)
 * Librerias: "Adafruit BME680 Library" y "Adafruit Unified Sensor"
 * La red esta en modelo_co2.h (generado por exportar_modelo.py) y co2_mlp.h.
 *
 * Como funciona:
 *  - Los sensores trabajan siempre con el mismo ciclo que esp32s3_logger (el BME688 con
 *    el mismo calentador), y siempre se actualiza el historial de la red.
 *  - Cada PASO_S segundos se calcula el promedio del ULTIMO MINUTO y se corre la red.
 *    Hay PASOS_MIN estimadores desfasados: cada uno recibe un promedio de 1 min por minuto,
 *    igual que en el entrenamiento, asi que la red ve lo mismo pero se publica cada PASO_S.
 *  - Solo se imprimen predicciones despues de "start".
 *
 * Protocolo serie (115200, una linea por mensaje, campos separados por coma):
 *   ESP32 -> PC
 *     #HOLA,CO2-MLP,<red>,<paso_s>       al arrancar y con "ping"
 *     #ESTADO,<0|1>                       1 = enviando predicciones
 *     #PRED,<s_desde_arranque>,<co2_ppm>,<fuera_de_rango>,<calentando 0|1>
 *     #AVISO,<texto>                      sensor sin datos, comando desconocido...
 *   PC -> ESP32
 *     start | stop | ping | mlp test
 *   fuera_de_rango: de las MLP_ENTRADAS entradas, cuantas quedan fuera de lo visto al entrenar.
 *   calentando = 1: todavia no hay 6 min de historial (las tendencias de 5 min valen 0).
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME680.h>
#include "co2_mlp.h"

// ======================= PINES =======================
constexpr int PIN_SDA    = 15;
constexpr int PIN_SCL    = 16;
constexpr int PIN_PMS_RX = 18;   // pin del ESP32 conectado al TX del PMS5003

// BME688: deben ser IGUALES a los de esp32s3_logger (con esos se grabaron los datos de entrenamiento)
constexpr uint16_t HEATER_TEMP_C  = 320;
constexpr uint16_t HEATER_MS      = 150;
constexpr uint32_t BME_PERIOD_MS  = 3000;

constexpr uint32_t PASO_S    = 5;               // cada cuanto se publica una prediccion
constexpr int      PASOS_MIN = 60 / PASO_S;     // pasos en un minuto (ventana del promedio)
constexpr uint32_t SERIAL_BAUD = 115200;

// ===================== ESTADO ========================
Adafruit_BME680 bme;
bool bmeOk = false;
bool enviando = false;
uint32_t nextBmeMs = 0, nextPasoMs = 0, pasos = 0;

// sumas de un paso: conteos n0_3...n10 del PMS y temp, HR, gas del BME
struct Paso {
  double pms[6]; uint32_t pmsN;
  double bme[3]; uint32_t bmeN;
};
Paso actual = {};
Paso anillo[PASOS_MIN] = {};   // ultimos PASOS_MIN pasos = ultimo minuto
EstimadorCO2 estimadores[PASOS_MIN];

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
          for (int i = 0; i < 6; i++)   // palabras 6-11: conteos por tamano
            actual.pms[i] += ((uint16_t)buf[16 + 2 * i] << 8) | buf[17 + 2 * i];
          actual.pmsN++;
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
  if ((int32_t)(now - nextBmeMs) > 0) nextBmeMs = now + BME_PERIOD_MS;
  if (!bme.performReading()) return;
  actual.bme[0] += bme.temperature;
  actual.bme[1] += bme.humidity;
  actual.bme[2] += bme.gas_resistance;
  actual.bmeN++;
}

// ================== ESTIMACION =======================
void pasoService() {
  if ((int32_t)(millis() - nextPasoMs) < 0) return;
  nextPasoMs += PASO_S * 1000UL;

  int fase = pasos % PASOS_MIN;
  anillo[fase] = actual;
  actual = {};
  pasos++;
  if (pasos < (uint32_t)PASOS_MIN) return;   // todavia no hay un minuto completo

  Paso minuto = {};
  for (int k = 0; k < PASOS_MIN; k++) {
    for (int i = 0; i < 6; i++) minuto.pms[i] += anillo[k].pms[i];
    for (int i = 0; i < 3; i++) minuto.bme[i] += anillo[k].bme[i];
    minuto.pmsN += anillo[k].pmsN;
    minuto.bmeN += anillo[k].bmeN;
  }
  if (!minuto.pmsN || !minuto.bmeN) {
    if (enviando) Serial.println(minuto.pmsN ? "#AVISO,sin datos del BME688 (SDA 15, SCL 16)"
                                             : "#AVISO,sin datos del PMS5003 (TX al pin 18, 5 V)");
    return;
  }
  MinutoCO2 m;
  for (int i = 0; i < 6; i++) m.n[i] = minuto.pms[i] / minuto.pmsN;
  m.tempC  = minuto.bme[0] / minuto.bmeN;
  m.rh     = minuto.bme[1] / minuto.bmeN;
  m.gasOhm = minuto.bme[2] / minuto.bmeN;

  EstimadorCO2& e = estimadores[fase];
  double co2 = e.agregarMinuto(m);
  if (enviando) {
    Serial.printf("#PRED,%lu,%.1f,%d,%d\n", (unsigned long)(millis() / 1000), co2, e.fueraDeRango,
                  e.minutos() <= MLP_VENTANA ? 1 : 0);
  }
}

// ================== COMANDOS =========================
void saludo() {
  Serial.printf("#HOLA,CO2-MLP,%s,%lu\n", MLP_NOMBRE, (unsigned long)PASO_S);
  Serial.printf("#ESTADO,%d\n", enviando ? 1 : 0);
}

void mlpTest() {
  for (int k = 0; k < MLP_N_PRUEBAS; k++) {
    double p = mlpPredecir(MLP_PRUEBA_X + k * MLP_ENTRADAS);
    Serial.printf("mlp test %d: ESP32 %.2f | Python %.2f | diferencia %.3f\n",
                  k, p, MLP_PRUEBA_Y[k], p - MLP_PRUEBA_Y[k]);
  }
}

void handleLine(String line) {
  line.trim();
  line.toLowerCase();
  if (!line.length()) return;
  if (line == "start")         { enviando = true;  Serial.println("#ESTADO,1"); }
  else if (line == "stop")     { enviando = false; Serial.println("#ESTADO,0"); }
  else if (line == "ping")     { saludo(); }
  else if (line == "mlp test") { mlpTest(); }
  else Serial.println("#AVISO,comando desconocido (start | stop | ping | mlp test)");
}

void readSerial() {
  static String buf;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) { handleLine(buf); buf = ""; }
    } else if (buf.length() < 60) {
      buf += c;
    }
  }
}

// ================== SETUP / LOOP =====================
void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(1500);

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
  nextBmeMs  = millis();
  nextPasoMs = millis() + PASO_S * 1000UL;

  saludo();
  if (!bmeOk) Serial.println("#AVISO,BME688 no detectado (SDA 15, SCL 16)");
}

void loop() {
  readSerial();
  pmsService();
  bmeService();
  pasoService();
  delay(2);
}
