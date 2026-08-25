// ======================================================================
// Google Apps Script - Inventory Export & RED Alert System
// LaundryRage / RageLabs Inventory Management
// ======================================================================
//
// Deploy instructions:
// 1. Open your Red Alerts Google Sheet:
//    https://docs.google.com/spreadsheets/d/16FRbThnUGaF4LX00OKH8YpCNbiZCaTKLK2_YpfaE_Vo/edit
// 2. Click Extensions > Apps Script.
// 3. Paste this entire script, replacing everything.
// 4. Update SECRET_TOKEN and ADMIN_EMAIL below.
// 5. Click Deploy > New Deployment. Select "Web App".
//    - Execute as: "Me"
//    - Who has access: "Anyone"
// 6. Copy the Web App URL into your Django .env:
//    GOOGLE_APPS_SCRIPT_URL="YOUR_WEB_APP_URL"
//    GOOGLE_SHEETS_EXPORT_URL="YOUR_WEB_APP_URL"
//    APPS_SCRIPT_SECRET="YOUR_SECRET_TOKEN"
// 7. Set up a Time-driven Trigger for dailyTrigger() at 6 AM daily.
// ======================================================================

var SECRET_TOKEN = "replace_with_a_secure_random_token";
var ADMIN_EMAIL  = "admin@example.com";

var BRANCH_SPREADSHEETS = {
  "OD3301LR-JGM": "1brVV0GHj-jI9A_ds_dFyiaQbGcqu2If6iboH6mok9tI",
  "OD3302LR-CSP": "1QqYwzk6WjIs2XWJP_S2TAWxKeaAWNv_OrD6MuobTC-4"
};

var RED_ALERTS_SPREADSHEET_ID = "16FRbThnUGaF4LX00OKH8YpCNbiZCaTKLK2_YpfaE_Vo";

function doGet(e) {
  return ContentService
    .createTextOutput("Inventory Google Sheets Export API is running.")
    .setMimeType(ContentService.MimeType.TEXT);
}

function doPost(e) {
  var data;
  try { data = JSON.parse(e.postData.contents); }
  catch (err) { return jsonResponse_({ success: false, error: "Invalid JSON" }); }

  // ── Authentication ────────────────────────────────────────────────────
  // All requests from Django must carry the correct secret_token.
  // This applies to: supplies, accessories, red_alerts, request_refill,
  // and send_daily_red_alert — every single route below.
  if (!data.secret_token || data.secret_token !== SECRET_TOKEN) {
    return jsonResponse_({ success: false, error: "Unauthorized" });
  }

  // 1. Manual refill request or daily red-alert trigger
  if (data.action === "request_refill" || data.action === "send_daily_red_alert") {
    var redSheet = getOrCreateRedAlertsSheet_();
    try {
      sendRefillEmail(redSheet, data.action === "request_refill");
      return jsonResponse_({ success: true });
    } catch (err) {
      return jsonResponse_({ success: false, error: err.toString() });
    }
  }

  // 2. Red Alerts export from Django
  if (data.category === "red_alerts" && data.records) {
    var ssId = data.spreadsheet_id || RED_ALERTS_SPREADSHEET_ID;
    var ss;
    try { ss = SpreadsheetApp.openById(ssId); }
    catch (err) { ss = SpreadsheetApp.getActiveSpreadsheet(); }
    var sheet = ss.getSheetByName("Red Alerts");
    if (!sheet) {
      sheet = ss.insertSheet("Red Alerts");
      sheet.appendRow(["Alert ID","Date","Time","Branch","Branch Code","Category",
        "Product","Current Stock","Base Stock","Refill Required","Status","Email Sent","Email Sent At"]);
    }
    for (var i = 0; i < data.records.length; i++) {
      var r = data.records[i];
      sheet.appendRow([r.alert_id,r.date,r.time,r.branch,r.branch_code,r.category,
        r.product,r.current_stock,r.base_stock,r.refill_required,r.status,r.email_sent||"NO",""]);
    }
    return jsonResponse_({ success: true, rows_added: data.records.length });
  }

  // 3. History export (supplies / accessories)
  if ((data.category === "supplies" || data.category === "accessories") && Array.isArray(data.records)) {
    var branchId      = data.branch_id || data.branch_code;
    var spreadsheetId = data.spreadsheet_id || BRANCH_SPREADSHEETS[branchId];
    if (!branchId || !spreadsheetId)
      return jsonResponse_({ success: false, error: "Invalid branch or missing spreadsheet mapping" });
    try {
      var ss        = SpreadsheetApp.openById(spreadsheetId);
      var sheetName = (data.category === "supplies") ? "Laundry Supplies History" : "Laundry Accessories History";
      var sheet     = ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);
      normalizeHeader_(sheet, ["Date","Product","Base Stock","Closing Stock","Remaining %","Status","Branch ID"]);

      var rows = sheet.getDataRange().getValues();
      var existingRows = Object.create(null);
      var lastDataRow  = 1;
      for (var rowIndex = 1; rowIndex < rows.length; rowIndex++) {
        var row = rows[rowIndex];
        if (row[0] !== "" || row[1] !== "") lastDataRow = rowIndex + 1;
        if (!row[0] && !row[1]) continue;
        var eb = row[6] || branchId;
        if (!row[6]) sheet.getRange(rowIndex + 1, 7).setValue(branchId);
        existingRows[eb + "||" + formatDate_(row[0]) + "||" + String(row[1]).trim()] = rowIndex + 1;
      }

      var incoming = Object.create(null);
      for (var i = 0; i < data.records.length; i++) {
        var rec = data.records[i];
        if (!rec || !rec.date || !rec.product) continue;
        incoming[branchId + "||" + formatDate_(rec.date) + "||" + String(rec.product).trim()] = rec;
      }

      var inserted = 0, updated = 0, toAppend = [];
      Object.keys(incoming).forEach(function(key) {
        var rec = incoming[key];
        var values = [[formatDate_(rec.date), String(rec.product).trim(), rec.base_stock,
          rec.closing_stock,
          rec.remaining_percentage != null ? rec.remaining_percentage : (rec.remaining_percent || "---"),
          rec.status, branchId]];
        if (typeof existingRows[key] === "number" && existingRows[key] > 0) {
          sheet.getRange(existingRows[key], 1, 1, 7).setValues(values); updated++;
        } else { toAppend.push(values[0]); inserted++; }
      });
      if (toAppend.length > 0)
        sheet.getRange(lastDataRow + 1, 1, toAppend.length, 7).setValues(toAppend);

      Logger.log("History export: branch=%s category=%s received=%s inserted=%s updated=%s",
        branchId, data.category, data.records.length, inserted, updated);
      return jsonResponse_({ success: true, branch_id: branchId, category: data.category,
        spreadsheet_id: spreadsheetId, sheet_name: sheetName,
        received: data.records.length, inserted: inserted, updated: updated,
        spreadsheet_url: "https://docs.google.com/spreadsheets/d/" + spreadsheetId + "/edit" });
    } catch (err) {
      Logger.log("History export failed: " + err);
      return jsonResponse_({ success: false, error: "Spreadsheet error: " + err.toString() });
    }
  }

  return jsonResponse_({ success: false, error: "Unknown request category or action" });
}

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------
function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
function formatDate_(value) {
  if (value instanceof Date) return Utilities.formatDate(value, "Asia/Kolkata", "yyyy-MM-dd");
  return String(value).slice(0, 10);
}
function normalizeHeader_(sheet, headers) {
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
}
function getOrCreateRedAlertsSheet_() {
  var ss;
  try { ss = SpreadsheetApp.openById(RED_ALERTS_SPREADSHEET_ID); }
  catch (err) { ss = SpreadsheetApp.getActiveSpreadsheet(); }
  var sheet = ss.getSheetByName("Red Alerts");
  if (!sheet) {
    sheet = ss.insertSheet("Red Alerts");
    sheet.appendRow(["Alert ID","Date","Time","Branch","Branch Code","Category",
      "Product","Current Stock","Base Stock","Refill Required","Status","Email Sent","Email Sent At"]);
  }
  return sheet;
}
function getLatestRedAlerts(sheet) {
  var rows = sheet.getDataRange().getValues();
  if (rows.length <= 1) return [];
  var latestMap = {};
  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    latestMap[row[4] + "||" + row[6]] = {
      rowIndex: i+1, alertId: row[0], dateVal: row[1], timeVal: row[2],
      branchName: row[3], branchCode: row[4], category: row[5], productName: row[6],
      currentStock: row[7], baseStock: row[8], refillRequired: row[9], status: row[10], emailSent: row[11]
    };
  }
  var redAlerts = [];
  for (var key in latestMap) {
    var a = latestMap[key];
    if (a.status === "RED" || a.status === "OUT_OF_STOCK") redAlerts.push(a);
  }
  return redAlerts;
}

// -----------------------------------------------------------------------
// Build and send RED alert email
// -----------------------------------------------------------------------
function sendRefillEmail(sheet, isManual) {
  var redAlerts = getLatestRedAlerts(sheet);
  if (!isManual) redAlerts = redAlerts.filter(function(a) { return a.emailSent !== "YES"; });
  if (redAlerts.length === 0) { Logger.log("No RED alerts to email."); return; }

  redAlerts.sort(function(a, b) {
    return a.category !== b.category ? a.category.localeCompare(b.category) : a.branchName.localeCompare(b.branchName);
  });

  var dateStr = Utilities.formatDate(new Date(), "Asia/Kolkata", "dd MMMM yyyy");
  var subject = (isManual ? "Inventory Refill Request" : "Daily Inventory Red Alert") + " -- " + dateStr;
  var title   = isManual ? "Inventory Refill Request" : "Daily Inventory Red Alert";
  var desc    = isManual ? "The following products require replenishment:" : "The following products require immediate replenishment.";

  var html = "<div style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:0 auto;padding:20px;border:1px solid #ddd;border-radius:8px;'>"
           + "<h2 style='color:#d9534f;margin-top:0;'>" + title + "</h2>"
           + "<p style='font-size:14px;'>" + desc + "</p>"
           + "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
           + "<thead><tr style='background:#f5f5f5;border-bottom:2px solid #ddd;'>"
           + "<th style='text-align:left;padding:8px;'>Branch</th><th style='text-align:left;padding:8px;'>Product</th>"
           + "<th style='text-align:right;padding:8px;'>Current</th><th style='text-align:right;padding:8px;'>Base</th>"
           + "<th style='text-align:right;padding:8px;'>Refill Required</th></tr></thead><tbody>";
  var text = title + "\n\n" + desc + "\n\nBranch | Product | Current | Base | Refill\n" + "-".repeat(60) + "\n";
  var totalRefill = 0;

  for (var i = 0; i < redAlerts.length; i++) {
    var a = redAlerts[i];
    html += "<tr style='border-bottom:1px solid #eee;'>"
          + "<td style='padding:8px;'><strong>" + a.branchName + "</strong><br/><span style='font-size:11px;color:#999;'>" + a.branchCode + "</span></td>"
          + "<td style='padding:8px;'>" + a.productName + "<br/><span style='font-size:11px;color:#999;'>" + a.category + "</span></td>"
          + "<td style='padding:8px;text-align:right;'>" + a.currentStock + "</td>"
          + "<td style='padding:8px;text-align:right;'>" + a.baseStock + "</td>"
          + "<td style='padding:8px;text-align:right;font-weight:bold;color:#d9534f;'>" + a.refillRequired + "</td></tr>";
    text += a.branchName + " (" + a.branchCode + ") | " + a.productName + " | " + a.currentStock + " | " + a.baseStock + " | " + a.refillRequired + "\n";
    totalRefill += Number(a.refillRequired);
  }
  html += "</tbody></table>"
        + "<div style='margin-top:16px;padding:12px;background:#fafafa;border:1px solid #eee;border-radius:6px;font-size:14px;'>"
        + "<p style='margin:4px 0;'><strong>Total RED products:</strong> " + redAlerts.length + "</p>"
        + "<p style='margin:4px 0;color:#d9534f;'><strong>Total refill required:</strong> " + totalRefill + " units</p></div>"
        + "<p style='font-size:12px;color:#999;margin-top:16px;'>Please review and arrange replenishment.</p></div>";
  text += "\nTotal RED: " + redAlerts.length + " | Total refill: " + totalRefill + " units";

  MailApp.sendEmail({ to: ADMIN_EMAIL, subject: subject, htmlBody: html, body: text });

  var sentAt = Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd HH:mm:ss");
  for (var i = 0; i < redAlerts.length; i++) {
    sheet.getRange(redAlerts[i].rowIndex, 12).setValue("YES");
    sheet.getRange(redAlerts[i].rowIndex, 13).setValue(sentAt);
  }
  Logger.log("RED alert email sent to " + ADMIN_EMAIL + " for " + redAlerts.length + " product(s).");
}

// -----------------------------------------------------------------------
// Time-driven trigger -- runs at 6 AM daily
// -----------------------------------------------------------------------
function dailyTrigger() {
  sendRefillEmail(getOrCreateRedAlertsSheet_(), false);
}
