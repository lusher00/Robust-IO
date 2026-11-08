// Robust IO bench fixture: board plus Raspberry Pi side by side on one plate.
// Pi sits to the right of the board (J1 ISP header is mid-board, J20 UART is on
// the right edge), with its 40-pin header edge toward the board so the ISP and
// UART leads stay short.
//
// Print flat. M3 and M2.5 holes are sized for heat-set inserts by default;
// set insert = false for plain screw holes (tap or self-thread).

// ---- parameters ----
insert       = true;      // heat-set inserts in the posts
plate_t      = 4;         // plate thickness
post_h       = 8;         // standoff height above the plate (board underside clearance)
gap          = 20;        // space between board edge and Pi edge
margin       = 6;         // plate overhang beyond the boards
corner_r     = 4;

// Robust IO: 160 x 100 board, 4 x M3 holes 5 mm in from each edge
rio_w = 160;  rio_h = 100;
rio_holes = [[5,5],[155,5],[5,95],[155,95]];
m3_insert_d = 4.0;  m3_screw_d = 2.5;

// Raspberry Pi 4 / 5: 85 x 56 board, 4 x M2.5 holes, 3.5 mm in, 58 x 49 pattern
pi_w = 85;   pi_h = 56;
pi_holes = [[3.5,3.5],[61.5,3.5],[3.5,52.5],[61.5,52.5]];
m25_insert_d = 3.4; m25_screw_d = 2.1;

post_d = 8;

// ---- derived ----
pi_x0 = rio_w + gap;                 // Pi left edge (Pi rotated so header edge faces the board)
plate_w = rio_w + gap + pi_h + 2*margin;   // Pi is rotated 90 deg: its 56 mm side runs along X
plate_h = max(rio_h, pi_w) + 2*margin;

module rounded_plate(w, h, t, r) {
    linear_extrude(t)
        offset(r) offset(-r) square([w, h]);
}

module post(hole_insert_d, hole_screw_d) {
    difference() {
        cylinder(d = post_d, h = plate_t + post_h, $fn = 40);
        translate([0,0,plate_t + post_h - (insert ? 6 : post_h + 1)])
            cylinder(d = insert ? hole_insert_d : hole_screw_d, h = 10, $fn = 24);
    }
}

// Pi mounted rotated 90 deg CCW about its own corner so the 40-pin header
// (along the 85 mm edge, 3.5 mm from the top-left in Pi coordinates) ends up
// facing the Robust IO board.
function pi_xy(p) = [pi_x0 + (pi_h - p[1]), p[0]];

translate([margin, margin, 0]) {
    difference() {
        translate([-margin, -margin, 0]) rounded_plate(plate_w, plate_h, plate_t, corner_r);
        // weight-saving cutouts under each board
        translate([20, 20, -1]) cube([rio_w - 40, rio_h - 40, plate_t + 2]);
        translate([pi_x0 + 12, 12, -1]) cube([pi_h - 24, pi_w - 24, plate_t + 2]);
    }
    for (p = rio_holes) translate([p[0], p[1], 0]) post(m3_insert_d, m3_screw_d);
    for (p = pi_holes)  translate([pi_xy(p)[0], pi_xy(p)[1], 0]) post(m25_insert_d, m25_screw_d);

    // label
    translate([rio_w/2, -margin + 1.5, plate_t]) linear_extrude(0.6)
        text("ROBUST IO", size = 4, halign = "center");
    translate([pi_x0 + pi_h/2, -margin + 1.5, plate_t]) linear_extrude(0.6)
        text("PI", size = 4, halign = "center");
}
