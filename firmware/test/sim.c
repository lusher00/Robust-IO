/* Robust IO firmware simulation on simavr.
 *
 * Runs build/robust-io.elf on a simulated ATmega1284P at 12 MHz with simple
 * models of the MC33978 and MCP2515 on the SPI bus, drives the console over
 * UART0 and prints everything the firmware sends, plus every CAN frame it
 * transmits ("CAN TX ...").
 *
 * The models implement only what the firmware uses. They are a check on the
 * firmware's logic and protocol handling, not on the real chips' timing.
 *
 * Usage: sim <elf> "<script>"   steps separated by ';'
 *   c:TEXT        type TEXT and Enter on the console
 *   w:MS          run for MS milliseconds
 *   rx:ID B0 ..   CAN frame from the bus (hex)
 *   in:HEX        MC33978 switch state (bits 0..21, 1 = closed)
 *   adc:CH:MV     voltage on ADC channel CH
 *   fault:1|0     DRV8876 nFAULT low (1) or released (0)
 *   ack:1|0       other nodes acknowledge CAN frames (default 1)
 *   mute:1|0      hide CAN TX lines
 *
 * Live mode: sim <elf> --udp PORT
 *   Runs in real time. CAN frames are exchanged over UDP on 127.0.0.1:PORT
 *   (tools/python/robustio/simbus.py is the client side); lines typed on
 *   stdin go to the console. Runs until stopped.
 *   Datagram format: 2 bytes ID (big-endian), 1 byte DLC, DLC data bytes.
 *   Every client that sends a datagram receives all transmitted frames (up to
 *   8 clients); a datagram with ID 0 only registers the client.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <simavr/sim_avr.h>
#include <simavr/sim_elf.h>
#include <simavr/avr_uart.h>
#include <simavr/avr_adc.h>
#include <simavr/avr_ioport.h>
#include <simavr/avr_spi.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>

#define F 12000000ULL
static avr_t *avr;
static avr_irq_t *spi_in, *int_can, *int_in;
static int cs_can = 1, cs_in = 1, ack = 1, mute = 0;
static int udp = -1, npeers = 0;
static struct sockaddr_in peers[8];                   /* every client that has sent a datagram */

static void add_peer(const struct sockaddr_in *a)
{
    for (int i = 0; i < npeers; i++)
        if (peers[i].sin_port == a->sin_port && peers[i].sin_addr.s_addr == a->sin_addr.s_addr) return;
    if (npeers < 8) peers[npeers++] = *a;
}

static double now_s(void) { return (double)avr->cycle / F; }

/* ---------------- MCP2515 ---------------- */
static uint8_t cr[128];
static int c_idx, c_cmd, c_addr, c_mask;

static void c_reset(void) { memset(cr, 0, sizeof cr); cr[0x0E] = 0x80; cr[0x0F] = 0x87; }
static void c_int(void) { avr_raise_irq(int_can, (cr[0x2C] & cr[0x2B]) ? 0 : 1); }
static void c_write(uint8_t a, uint8_t v)
{
    cr[a & 0x7F] = v;
    if ((a & 0x7F) == 0x0F) {
        cr[0x0E] = (uint8_t)((cr[0x0E] & 0x1F) | (v & 0xE0));
        if (v & 0x10) { cr[0x30] &= ~0x08; cr[0x40] &= ~0x08; cr[0x50] &= ~0x08; }
    }
    c_int();
}
static uint8_t c_status(void)
{
    return (uint8_t)((cr[0x2C] & 1) | (cr[0x2C] & 2) | ((cr[0x30] & 8) ? 4 : 0) |
                     ((cr[0x40] & 8) ? 0x10 : 0) | ((cr[0x50] & 8) ? 0x40 : 0));
}
static void c_to_rx(uint8_t sidh, uint8_t sidl, uint8_t dlc, const uint8_t *d)
{
    uint8_t base;
    if (!(cr[0x2C] & 1)) { base = 0x61; cr[0x2C] |= 1; }
    else if (!(cr[0x2C] & 2)) { base = 0x71; cr[0x2C] |= 2; }
    else { printf("[sim] CAN RX overflow\n"); return; }
    cr[base] = sidh; cr[base + 1] = sidl; cr[base + 4] = dlc;
    memcpy(&cr[base + 5], d, dlc & 15);
    c_int();
}
static void c_transmit(void)
{
    uint8_t mode = cr[0x0E] & 0xE0;
    for (int b = 2; b >= 0; b--) {                      /* TXB2 has priority on ties */
        uint8_t c = (uint8_t)(0x30 + 0x10 * b);
        if (!(cr[c] & 8)) continue;
        if (mode == 0x40) {
            c_to_rx(cr[c + 1], cr[c + 2], cr[c + 5], &cr[c + 6]);
        } else if (mode == 0x00) {
            if (!ack) continue;                         /* stays pending, no acknowledge */
            if (udp >= 0) {
                if (!npeers) continue;                  /* nobody listening: no acknowledge */
                uint8_t pkt[11];
                uint16_t id = (uint16_t)((cr[c + 1] << 3) | (cr[c + 2] >> 5));
                pkt[0] = (uint8_t)(id >> 8); pkt[1] = (uint8_t)id; pkt[2] = cr[c + 5] & 15;
                memcpy(&pkt[3], &cr[c + 6], pkt[2] > 8 ? 8 : pkt[2]);
                for (int k = 0; k < npeers; k++)
                    sendto(udp, pkt, 3u + (pkt[2] > 8 ? 8 : pkt[2]), 0, (struct sockaddr *)&peers[k], sizeof peers[k]);
            } else if (!mute) {
                printf("[%7.3f] CAN TX %03X [%u]", now_s(), (cr[c + 1] << 3) | (cr[c + 2] >> 5), cr[c + 5] & 15);
                for (int i = 0; i < (cr[c + 5] & 15); i++) printf(" %02X", cr[c + 6 + i]);
                printf("\n");
            }
        } else continue;
        cr[c] &= ~8;
    }
}
static uint8_t c_byte(uint8_t in)
{
    uint8_t out = 0;
    if (c_idx == 0) c_cmd = in;
    else switch (c_cmd) {
    case 0x03: if (c_idx == 1) c_addr = in; else out = cr[(c_addr++) & 0x7F]; break;
    case 0x02: if (c_idx == 1) c_addr = in; else c_write((uint8_t)c_addr++, in); break;
    case 0x05: if (c_idx == 1) c_addr = in; else if (c_idx == 2) c_mask = in;
               else if (c_idx == 3) c_write((uint8_t)c_addr, (uint8_t)((cr[c_addr & 0x7F] & ~c_mask) | (in & c_mask))); break;
    case 0xA0: out = c_status(); break;
    default: break;
    }
    c_idx++;
    return out;
}
static void c_cs(int level)
{
    if (!level) { c_idx = 0; return; }
    if (c_cmd == 0xC0 && c_idx >= 1) c_reset();
    if ((c_cmd & 0xF8) == 0x80 && c_idx >= 1) {
        if (c_cmd & 1) cr[0x30] |= 8;
        if (c_cmd & 2) cr[0x40] |= 8;
        if (c_cmd & 4) cr[0x50] |= 8;
    }
    c_transmit();
    c_cmd = -1;
}

/* ---------------- MC33978 ---------------- */
static uint32_t mr[64], m_in, m_out, m_next, m_inputs, m_fault = 1;
static int m_idx, m_intpend;

static void m_int(void) { avr_raise_irq(int_in, m_intpend ? 0 : 1); }
static uint8_t m_byte(uint8_t in)
{
    uint8_t out = (uint8_t)(m_out >> (24 - 8 * m_idx));
    m_in = (m_in << 8) | in;
    m_idx++;
    return out;
}
static void m_cs(int level)
{
    if (!level) { m_idx = 0; m_in = 0; m_out = m_next; return; }
    if (m_idx != 4) { printf("[sim] MC33978 frame of %d bytes\n", m_idx); return; }
    uint8_t cmd = (uint8_t)(m_in >> 24), addr = cmd >> 1;
    uint32_t data = m_in & 0xFFFFFF, flags = m_fault ? (1UL << 23) : 0;
    if (cmd == 0x00) { m_next = 0x00123456; return; }
    if (cmd & 1) {                                     /* write */
        mr[addr] = data;
        m_next = (0x3EUL << 24) | flags | m_inputs;
        return;
    }
    if (cmd == 0x3E) { m_next = (0x3EUL << 24) | flags | m_inputs; m_intpend = 0; m_int(); return; }
    if (cmd == 0x42) { m_next = (0x42UL << 24) | flags | m_fault; m_fault = 0; return; }
    m_next = ((uint32_t)cmd << 24) | flags | mr[addr];
}

/* ---------------- glue ---------------- */
static void spi_out(struct avr_irq_t *irq, uint32_t v, void *p)
{
    (void)irq; (void)p;
    uint8_t r = 0xFF;
    if (!cs_can && !cs_in) printf("[sim] BOTH chip selects low\n");
    if (!cs_can) r = c_byte((uint8_t)v);
    else if (!cs_in) r = m_byte((uint8_t)v);
    avr_raise_irq(spi_in, r);
}
static void pin_b0(struct avr_irq_t *irq, uint32_t v, void *p) { (void)irq; (void)p; if ((int)v != cs_can) { cs_can = (int)v; c_cs(cs_can); } }
static void pin_b1(struct avr_irq_t *irq, uint32_t v, void *p) { (void)irq; (void)p; if ((int)v != cs_in)  { cs_in  = (int)v; m_cs(cs_in);  } }

static int col0 = 1;
static void uart_out(struct avr_irq_t *irq, uint32_t v, void *p)
{
    (void)irq; (void)p;
    if (v == '\r') return;
    putchar((int)v);
    col0 = (v == '\n');
}

static void run_ms(double ms)
{
    avr_cycle_count_t end = avr->cycle + (avr_cycle_count_t)(ms * F / 1000.0);
    while (avr->cycle < end) {
        int s = avr_run(avr);
        if (s == cpu_Done || s == cpu_Crashed) { printf("\n[sim] CPU stopped (%d)\n", s); exit(1); }
    }
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: sim <elf> \"<script>\"\n"); return 2; }
    elf_firmware_t f; memset(&f, 0, sizeof f);
    if (elf_read_firmware(argv[1], &f)) return 2;
    avr = avr_make_mcu_by_name("atmega1284p");
    avr_init(avr);
    f.frequency = F;
    avr_load_firmware(avr, &f);
    avr->frequency = F;
    avr->avcc = avr->aref = avr->vcc = 3300;
    avr->log = 0;

    uint32_t fl = 0;
    avr_ioctl(avr, AVR_IOCTL_UART_GET_FLAGS('0'), &fl);
    fl &= ~AVR_UART_FLAG_STDIO;
    avr_ioctl(avr, AVR_IOCTL_UART_SET_FLAGS('0'), &fl);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT), uart_out, NULL);
    avr_irq_t *uin = avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_INPUT);

    spi_in = avr_io_getirq(avr, AVR_IOCTL_SPI_GETIRQ(0), SPI_IRQ_INPUT);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_SPI_GETIRQ(0), SPI_IRQ_OUTPUT), spi_out, NULL);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('B'), 0), pin_b0, NULL);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('B'), 1), pin_b1, NULL);
    int_can = avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('D'), 2);
    int_in  = avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('B'), 2);
    avr_irq_t *nfault = avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ('D'), 3);

    c_reset();
    mr[0x01] = 0x0008FF;                               /* device config power-on value */
    avr_raise_irq(int_can, 1);
    avr_raise_irq(int_in, 1);
    avr_raise_irq(nfault, 1);
    for (int ch = 0; ch < 8; ch++) avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + ch), 0);

    if (!strcmp(argv[2], "--udp")) {
        if (argc < 4) { fprintf(stderr, "usage: sim <elf> --udp PORT\n"); return 2; }
        udp = socket(AF_INET, SOCK_DGRAM, 0);
        struct sockaddr_in a; memset(&a, 0, sizeof a);
        a.sin_family = AF_INET; a.sin_port = htons((uint16_t)atoi(argv[3]));
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (bind(udp, (struct sockaddr *)&a, sizeof a)) { perror("bind"); return 2; }
        fcntl(udp, F_SETFL, O_NONBLOCK);
        fcntl(0, F_SETFL, O_NONBLOCK);
        printf("[sim] live, CAN on udp 127.0.0.1:%s, console on stdin\n", argv[3]);
        fflush(stdout);
        struct timespec t0; clock_gettime(CLOCK_MONOTONIC, &t0);
        char line[128]; int ll = 0;
        for (;;) {
            run_ms(1);
            uint8_t pkt[64];
            struct sockaddr_in from; socklen_t fl = sizeof from;
            ssize_t n;
            while ((n = recvfrom(udp, pkt, sizeof pkt, 0, (struct sockaddr *)&from, &fl)) > 0) {
                add_peer(&from);
                if (n >= 3 && pkt[2] <= 8 && n >= 3 + pkt[2] && (pkt[0] | pkt[1])) {   /* ID 0 = hello only */
                    uint16_t id = (uint16_t)((pkt[0] << 8) | pkt[1]);
                    c_to_rx((uint8_t)(id >> 3), (uint8_t)(id << 5), pkt[2], &pkt[3]);
                }
                fl = sizeof from;
            }
            char ch;
            while (read(0, &ch, 1) == 1) {
                if (ch == '\n') { for (int i = 0; i < ll; i++) { avr_raise_irq(uin, (uint8_t)line[i]); run_ms(0.2); } avr_raise_irq(uin, '\r'); ll = 0; }
                else if (ll < (int)sizeof line - 1) line[ll++] = ch;
            }
            fflush(stdout);
            /* pace to wall clock */
            struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
            double wall = (t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
            double ahead = now_s() - wall;
            if (ahead > 0.001) { struct timespec d = { 0, (long)(ahead * 1e9) }; nanosleep(&d, NULL); }
        }
    }

    int booted = 0;
    char *script = strdup(argv[2]);
    for (char *step = strtok(script, ";"); step; step = strtok(NULL, ";")) {
        while (*step == ' ') step++;
        if (!booted && strncmp(step, "mute:", 5) && strncmp(step, "ack:", 4)) { run_ms(300); booted = 1; }
        if (!strncmp(step, "c:", 2)) {
            for (char *p = step + 2; ; p++) {
                avr_raise_irq(uin, *p ? (uint8_t)*p : '\r');
                run_ms(0.2);
                if (!*p) break;
            }
            run_ms(50);
        } else if (!strncmp(step, "w:", 2)) {
            run_ms(atof(step + 2));
        } else if (!strncmp(step, "rx:", 3)) {
            char *e; unsigned id = (unsigned)strtoul(step + 3, &e, 16);
            uint8_t d[8]; int n = 0;
            while (n < 8) { char *e2; unsigned long b = strtoul(e, &e2, 16); if (e2 == e) break; d[n++] = (uint8_t)b; e = e2; }
            if (!col0) putchar('\n');
            printf("[%7.3f] CAN RX %03X [%d]", now_s(), id, n);
            for (int i = 0; i < n; i++) printf(" %02X", d[i]);
            printf("\n");
            c_to_rx((uint8_t)(id >> 3), (uint8_t)(id << 5), (uint8_t)n, d);
        } else if (!strncmp(step, "in:", 3)) {
            m_inputs = (uint32_t)strtoul(step + 3, NULL, 16) & 0x3FFFFF;
            m_intpend = 1; m_int();
        } else if (!strncmp(step, "adc:", 4)) {
            int ch = atoi(step + 4); char *m = strchr(step + 4, ':');
            avr_raise_irq(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + ch), m ? (uint32_t)atoi(m + 1) : 0);
        } else if (!strncmp(step, "fault:", 6)) {
            avr_raise_irq(nfault, atoi(step + 6) ? 0 : 1);
        } else if (!strncmp(step, "ack:", 4)) {
            ack = atoi(step + 4);
        } else if (!strncmp(step, "mute:", 5)) {
            mute = atoi(step + 5);
        } else if (*step) {
            fprintf(stderr, "unknown step: %s\n", step); return 2;
        }
    }
    printf("\n[sim] end at %.3f s\n", now_s());
    return 0;
}
