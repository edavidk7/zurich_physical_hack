## 1. Purpose

This procedure describes how to verify that the 5 V output pin of the Arduino Uno R3 supplies the correct regulated voltage, using a standard digital multimeter (DMM). The test is a non-destructive, in-circuit inspection and requires no firmware upload or code execution.

## 2. Background

When  powered  via  USB,  the  Arduino  Uno  R3  receives  5  V  directly  from  the  host  bus.  When powered via the barrel jack, an onboard NCP1117ST50T3G linear voltage regulator steps the input voltage (7-12 V) down to a stable 5 V rail . This rail is exposed on the 5V pin (power header J1, pin 4) and serves as the primary supply for the ATmega328P microcontroller and all 5 V peripherals.

A voltage outside the specified tolerance indicates a fault in the USB supply, the onboard regulator, a solder defect, or an excessive load. This inspection must be performed before connecting any 5 V-sensitive peripheral.

## 3. Required Equipment

|   Item | Description              | Specification / Notes                                 |
|--------|--------------------------|-------------------------------------------------------|
|      1 | Digital Multimeter (DMM) | DC voltage mode, accuracy ±0.5% or better             |
|      2 | Test leads               | Standard banana-plug leads supplied with DMM          |
|      3 | USB cable                | USB Type-A to Type-B, connected to a powered USB host |
|      4 | Arduino Uno R3           | Board under test - no shield or peripheral attached   |

NOTE: No peripheral, shield, or load must be connected to the 5V pin during this measurement. An external load will cause a voltage drop and produce a misleading reading.

## 4. Pin Location on the Board

Locate the power header (J1) on the Arduino Uno R3. It is the 8-pin single-row female header situated near the barrel jack connector. The 5V pin is the fourth pin from the end closest to the barrel jack, labelled "5V" in the silkscreen.

| Pin No.   | Label   | Function                  |
|-----------|---------|---------------------------|
| J1-1      | IOREF   | I/O reference voltage (~5 |
| J1-2      | RESET   | Active-low reset          |

## Arduino Uno R3 5 V Pin Voltage Verification

Multimeter Inspection Procedure Document No. ARD-TST-002  |  Revision 1.0  |  March 2026

| J1-3   | 3V3   | 3.3 V regulated output   |
|--------|-------|--------------------------|
| J1-4   | 5V    | 5 V supply ‹ TEST POINT  |
| J1-5   | GND   | Ground                   |
| J1-6   | GND   | Ground                   |
| J1-7   | VIN   | External supply input    |

## 5. Acceptance Criteria

The 5V pin output must fall within the following limits under no-load conditions:

| Parameter                                    | Min   | Nominal   |    Max | Unit   |
|----------------------------------------------|-------|-----------|--------|--------|
| 5V Pin Output Voltage (USB powered, no load) | 4.75  | 5.00      |   5.25 | V DC   |
| 5V Pin Output Voltage (barrel jack powered)  | 4.75  | 5.00      |   5.25 | V DC   |
| Max Rated Output Current                     | -     | -         | 500    | mA     |

## 6. Test Procedure

## Step 1 - Prepare the board

Ensure no shield, peripheral, or external wiring is attached to the Arduino. The board should be bare with only the USB cable connected.

## Step 2 - Power the board

Connect the Arduino to a USB host (PC, laptop, or powered USB hub) using the USB Type-A to Type-B cable. Confirm the green PWR LED illuminates steadily. Do not use the barrel jack for this test.

## Step 3 - Configure the DMM

Set the DMM selector to DC Voltage (V-) mode. If the meter is not auto-ranging, select the range . Insert the red probe into the V/ W terminal and the black probe into the COM terminal.

## Step 4 - Connect the negative probe

Touch  the black  (COM)  probe firmly  to  any GND  pin on  the  board  (e.g.  J1-5  or  J1-6,  labelled GND). Maintain steady contact throughout the measurement.

## Step 5 - Connect the positive probe

Touch the red probe firmly to the 5V pin (J1-4) . Ensure the probe tip makes clean contact with the metal pin and does not bridge to an adjacent pin.

## Step 6 - Read and record the voltage

Allow the DMM reading to stabilise (typically &lt;2 seconds). Read and record the displayed voltage to two decimal places.

10 V

## Step 7 - Evaluate the result

Compare the recorded voltage against the acceptance criteria in Section 5. A reading of 4.75 V 5.25 V constitutes a PASS . Any reading outside this range constitutes a FAIL - refer to Section 7.

## Step 8 - Disconnect

Remove both probes and disconnect the USB cable. Document the result in the test record (Section 8).

WARNING: Never connect the DMM probes across a live voltage source in resistance ( W ) or continuity mode. Always verify the DMM is set to DC Voltage before making contact with the board.

## 7. Fault Diagnosis

If the measured voltage falls outside 4.75 V - 5.25 V, perform the checks below in order before concluding that the board is defective.

| Symptom                               | Likely Cause                   | Corrective Action                                                                             |
|---------------------------------------|--------------------------------|-----------------------------------------------------------------------------------------------|
| Voltage below 4.75 V (e.g. 4.2-4.6 V) | Excessive load, weak USB host, | or degraded regulator Disconnect all peripherals and re-measure. Try a different USB          |
| Voltage = 0 V                         | No power input, blown          | polyfuse, or open solder joint Check USB cabl and host port. Inspect polyfuse F1 for continui |
| Voltage above 5.25 V (e.g. 5.4-5.8 V) | Regulator fault or incorrect   | barrel-jack supply Ve ify barrel-jack input is within 7-12 V. If using USB and vol            |
| Unstable / fluctuating                | Poor probe contact, loose USB  | connector, or marginal supply Clean pin with IPA and retry. Reseat USB cable. If still unstab |

## 8. Test Record

Complete the following record upon finishing the inspection. Retain this record as part of the device history file.

| Field                          | Entry                                             |
|--------------------------------|---------------------------------------------------|
| Board Serial / Asset No.       |                                                   |
| Date of Inspection             |                                                   |
| Inspector Name                 |                                                   |
| DMM Model & Serial No.         |                                                   |
| DMM Last Calibration Date      |                                                   |
| USB Supply Used                |                                                   |
| Measured 5V Pin Voltage (V DC) |                                                   |
| Result                         | &#x25A1; PASS (4.75-5.25 V) &#x25A1; FAIL (out of |

| Remarks / Observations   |
|--------------------------|

This document is provided for informational purposes only. Arduino is a trademark of Arduino AG. Always observe ESD precautions when handling bare PCBs.