#pragma once
#include <math.h>
#include <zephyr/kernel.h>

#include <cstdint>
#include <cstdlib>
#include <cstring>
// RadioHead uses this only for optional CAD backoff, never for security.
inline long random(long lo, long hi) {
    return hi > lo ? lo + k_cycle_get_32() % (hi - lo) : lo;
}
#define PROGMEM
#define memcpy_P memcpy
#define SS 38
#define INPUT 0
#define OUTPUT 1
#define HIGH 1
#define LOW 0
#define FALLING 2
#define NOT_AN_INTERRUPT -1
inline uint32_t millis() {
    return k_uptime_get_32();
}
inline void delay(unsigned long ms) {
    k_msleep(ms);
}
inline void yield() {
    k_msleep(1);
}
inline int digitalPinToInterrupt(int p) {
    return p;
}
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);
int digitalRead(uint8_t pin);
// RH's ISR is deliberately not attached: the worker calls serviceInterrupt().
inline void attachInterrupt(int, void (*)(), int) {}
inline void detachInterrupt(int) {}
class RHGenericSPI;
extern RHGenericSPI& hardware_spi;
