#!/usr/bin/env python3
from analyzer_dict import regex_patterns, solutions
from collections import OrderedDict
import datetime
import argparse
import re
import os
import tabulate
import tarfile
import gzip
from histogram import *

# Command line arguments

parser = argparse.ArgumentParser(description="Log Analyzer for YugabyteDB logs")
parser.add_argument("-l", "--log_files", nargs='+', help="List of log file[s]")
parser.add_argument("-d", "--directory", help="Directory containing log files")
parser.add_argument("--support_bundle", help="Path to support bundle")
parser.add_argument("-H", "--histogram", action="store_true", help="Generate histogram graph")
parser.add_argument("-wc",'--word_count', action="store_true",help='List top 20 word count')
parser.add_argument('-A','--ALL', action="store_true", help='FULL Health Check')
parser.add_argument("-t", "--from_time", metavar= "MMDD HH:MM", dest="start_time", help="Specify start time")
parser.add_argument("-T", "--to_time", metavar= "MMDD HH:MM", dest="end_time", help="Specify end time")
parser.add_argument("-s", "--sort-by", dest="sort_by", choices=['NO','LO','FO'], help="Sort by: \n NO = Number of occurrences, \n LO = Last Occurrence,\n FO = First Occurrence(Default)")
parser.add_argument("--html", action="store_true", help="Generate HTML report")
args = parser.parse_args()

# Validated start and end time format

if args.start_time:
    try:
        datetime.datetime.strptime(args.start_time, "%m%d %H:%M")
    except ValueError as e:
        print("Incorrect start time format, should be MMDD HH:MM")
        exit(1)
if args.end_time:
    try:
        datetime.datetime.strptime(args.end_time, "%m%d %H:%M")
    except ValueError as e:
        print("Incorrect end time format, should be MMDD HH:MM")
        exit(1)

start_time = datetime.datetime.strptime(args.start_time, "%m%d %H:%M") if args.start_time else None
end_time = datetime.datetime.strptime(args.end_time, "%m%d %H:%M") if args.end_time else None
htmlHeader = """
<!DOCTYPE html>
<html>
<head>
    <script src="https://www.kryogenix.org/code/browser/sorttable/sorttable.js"></script>
	<meta charset="utf-8">
	<title>Log Analysis Results</title>
    <script type="text/javascript">
    window.onload = function() {
		var toc = document.getElementById("toc");
			var headings = document.getElementsByTagName("h2");
			for (var i = 0; i < headings.length; i++) {
				var heading = headings[i];
				var anchor = document.createElement("a");
				anchor.href = "#" + heading.id;
				anchor.innerHTML = heading.innerHTML;
				var li = document.createElement("li");
				li.appendChild(anchor);
				toc.appendChild(li); 
			}
      var rows = document.querySelectorAll("#main-table tbody tr");
      for (var i = 0; i < rows.length; i++) {
        rows[i].onclick = function() {
          var rowHeading = this.querySelector("td:nth-of-type(2)").innerHTML;
          var targetHeading = document.getElementById(rowHeading.toLowerCase().replace(/\s/g, "-").replace(/-+$/, ""));
          if (targetHeading) {
            var targetOffset = targetHeading.offsetTop - 10;
            window.scrollTo(0, targetOffset);
			// highlight the the heading and its content for 2 seconds with #C6C6C6 background color and with good animation
			targetHeading.style.backgroundColor = "#C6C6C6";
			targetHeading.style.transition = "background-color 1s ease-in-out";
			var targetContent = targetHeading.nextElementSibling;
			targetContent.style.backgroundColor = "#C6C6C6";
			targetContent.style.transition = "background-color 1s ease-in-out";
			setTimeout(function() {
			  targetHeading.style.backgroundColor = "";
			  targetContent.style.backgroundColor = "";
			}, 2000);
          }
        }
      }
    }
    </script>
	<style>
		body {
			font-family: Arial, sans-serif;
			background-color: #f0f0f0;
            margin-left: 20px;
            line-height: 1.5;
		}
		h2, h3 {
			margin-top: 30px;
			margin-bottom: 15px;
            margin-left: 20px;
			color: #2d3c4d;
		}
		table {
			border-collapse: collapse;
			margin-top: 10px;
			margin-bottom: 30px;
			background-color: white;
			box-shadow: 0 5px 20px rgba(0,0,0,0.3);
			margin-left: 25px;
			margin-right: 25px;
			border-radius: 10px;
			overflow:hidden;
		}
		th, td {
			padding: 10px;
			text-align: left;
			border-bottom: 1px solid #ddd;
			font-size: 15px;
			color: #2d3c4d;
		}
		th {
			background-color: #f2f2f2;
			font-weight: bold;
			cursor: pointer;
		}
		tr:hover {
			background-color: #f5f5f5;
            cursor: pointer;
		}
		a {
			color: #0e7cd4;
			text-decoration: none;
		}
		a:hover {
			text-decoration: underline;
		}
        li {
			text-align: left;
		}
        p {
			margin-left: 20px;
		}
        #toc {
            position:relative;
            top: 0;
            width: auto;
            height: 100%;
            overflow: auto;
            background-color: #f0f0f0;
            margin-left: 25px;
          }
	</style>
</head>"""   # Thanks bing for beautifying the HTML report https://tinyurl.com/2l3hskkl :)

toc = """<div id="toc">
	<h2>Table of Contents</h2>
</div>"""

listOfErrorsInAllFiles = []
listOfErrorsInFile = []

if args.html:
    outputFile = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + "_analysis.html"
    open(outputFile, "w").write(htmlHeader)
    open(outputFile, "a").write(toc)
else:
    outputFile = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + "_analysis.txt"

def getLogFilesFromCommandLine():
    logFiles = []
    for file in args.log_files:
        # Check if this is file or directory
        if os.path.isfile(file):
            logFiles.append(file)
    return logFiles

def getLogFilesFromDirectory(logDirectory):
    logFiles = []
    for root, dirs, files in os.walk(logDirectory):
        for file in files:
            if file.__contains__("INFO") and file[0] != ".":
                logFiles.append(os.path.join(root, file))
    return logFiles

def getLogFilesFromSupportBundle(supportBundle):
    logFiles = []
    if supportBundle.endswith(".tar.gz"):
        tarFile=tarfile.open(supportBundle, "r:gz")
        support_bundle="support_bundle_{}".format(datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
        tarFile.extractall(support_bundle)
        tarFile.close()
        logFiles = getLogFilesFromDirectory(support_bundle)
    else:
        logFiles = getLogFilesFromDirectory(supportBundle)
    return logFiles

def getTimeFromLog(line):
    timeFromLog = line.split(" ")[0][1:] + " " + line.split(" ")[1][:5]
    timestamp = datetime.datetime.strptime(timeFromLog, "%m%d %H:%M")
    return timestamp

def analyzeLogFiles(logFile, start_time=None, end_time=None):
    try:
        lines = logFile.readlines()                                                                                                             # Read all the lines in the log file
    except UnicodeDecodeError as e:
        print("Skipping file {} as it is not a text file".format(logFile.name))
        return
    results = {}                                                                                                                      # Dictionary to store the results
    for line in lines:                                                                                                                # For each line in the log file           
        for message, pattern in regex_patterns.items():                                                                                     # For each message and pattern
            match = re.search(pattern, line)                                                                                                # Search for the pattern in the line
            if match and (not start_time or getTimeFromLog(line) >= start_time) and (not end_time or getTimeFromLog(line) <= end_time):     # If the pattern is found in the line and the line is within the time range          
                if message not in results:                                                                                                     # If the message is not in the results dictionary, add it
                    results[message] = {                                                                                                           # Initialize the dictionary for the message
                        "numOccurrences": 0,                                                                                                          # Number of occurrences of the message
                        "firstOccurrenceTime": None,                                                                                                 # Time of the first occurrence of the message
                        "lastOccurrenceTime": None,                                                                                                  # Time of the last occurrence of the message
                    }                                                                                                                              # End of dictionary for the message            
                results[message]["numOccurrences"] += 1                                                                                       # Increment the number of occurrences of the message
                time = line.split()[0][1:] + " " + line.split()[1]                                                                             # Get the time from the log line
                if not results[message]["firstOccurrenceTime"]:                                                                              # If the first occurrence time is not set
                    results[message]["firstOccurrenceTime"] = time                                                                               # set it 
                results[message]["lastOccurrenceTime"] = time                                                                                # Set time as last occurrence time
                listOfErrorsInFile.append(message)

    if args.sort_by == 'NO':
        sortedDict = OrderedDict(sorted(results.items(), key=lambda x: x[1]["numOccurrences"], reverse=True))
    elif args.sort_by == 'LO':
        sortedDict = OrderedDict(sorted(results.items(), key=lambda x: x[1]["lastOccurrenceTime"]))
    elif args.sort_by == 'FO' or True:
        sortedDict = OrderedDict(sorted(results.items(), key=lambda x: x[1]["firstOccurrenceTime"]))
    table = []
    message_id = 0
    for message, info in sortedDict.items():
        table.append(
            [
                info["numOccurrences"],
                message,
                info["firstOccurrenceTime"],
                info["lastOccurrenceTime"],
            ]
        )
    return table, listOfErrorsInFile
    
def get_histogram(logFile):
   print ("\nHistogram of logs creating time period\n")
   histogram(logFile)
   
def get_word_count(logFile):
   print ("\nMost widely used word in logs\n")
   word_count(logFile)

def getSolution(message):
    return solutions[message]
    
if __name__ == "__main__":
    
    filesWithNoErrors = []

    if args.log_files:
        logFileList = getLogFilesFromCommandLine()
    elif args.directory:
        logFileList = getLogFilesFromDirectory(args.directory)
    elif args.support_bundle:
        logFileList = getLogFilesFromSupportBundle(args.support_bundle)
    else:
        print("Please specify a log file, directory or support bundle")
        exit(1)

    if type(logFileList) is not list:
        print("No log files found")
        exit(1)
        
    for logFile in logFileList:
        if logFile.endswith(".gz"):
            with gzip.open(logFile, "rt") as f:
                table, listOfErrorsInFile = analyzeLogFiles(f, start_time, end_time)        
        else:
            with open(logFile, "r") as f:
                table, listOfErrorsInFile = analyzeLogFiles(f, start_time, end_time)
        if table:
            if args.html:
                formatLogFileForHTMLId = logFile.replace("/", "-").replace(".", "-").replace(" ", "-").replace(":", "-")
                open(outputFile, "a").write("<h2 id=" + formatLogFileForHTMLId + ">" + logFile + "</h2>")
                content = tabulate.tabulate(table, headers=["Occurrences", "Message", "First Occurrence", "Last Occurrence"], tablefmt="html")
                content = content.replace("$line-break$", "<br>").replace("$tab$", "&nbsp;&nbsp;&nbsp;&nbsp;").replace("$start-code$", "<code>").replace("$end-code$", "</code>").replace("$start-bold$", "<b>").replace("$end-bold$", "</b>").replace("$start-italic$", "<i>").replace("$end-italic$", "</i>").replace("<table>", "<table class='sortable' id='main-table'>")
                open(outputFile, "a").write(content)
            else:
                open(outputFile, "a").write("\n\n\nAnalysis of " + logFile + "\n\n")
                content = tabulate.tabulate(table, headers=["Occurrences", "Message", "First Occurrence", "Last Occurrence"], tablefmt="simple_grid")
                content = content.replace("$line-break$", "\n").replace("$tab$", "\t").replace("$start-code$", "`").replace("$end-code$", "`").replace("$start-bold$", "**").replace("$end-bold$", "**").replace("$start-italic$", "*").replace("$end-italic$", "*")
                open(outputFile, "a").write(content)
        else:
            filesWithNoErrors.append(logFile)
        # Merge the list of errors in this file with the global list of errors
        listOfErrorsInAllFiles = list(set(listOfErrorsInAllFiles) | set(listOfErrorsInFile))
        
    if listOfErrorsInAllFiles:
        open(outputFile, "a").write("<h2 id=troubleshooting-tips> Troubleshooting Tips </h2>")
        for error in listOfErrorsInAllFiles:
            solution = getSolution(error)
            formatErrorForHTMLId = error.replace(" ", "-").lower()
            open(outputFile, "a").write("<h3 id=" + formatErrorForHTMLId + ">" + error + " </h3>")
            content = solution.replace("$line-break$", "<br>").replace("$tab$", "&nbsp;&nbsp;&nbsp;&nbsp;").replace("$start-code$", "<code>").replace("$end-code$", "</code>")
            content = content.replace("$start-bold$", "<b>").replace("$end-bold$", "</b>").replace("$start-italic$", "<i>").replace("$end-italic$", "</i>")
            content = content.replace("$start-link$", "<a href='").replace("$end-link$", "' target='_blank'>").replace("$end-link-text$", "</a>")
            open(outputFile, "a").write( "<p>" + content + " </p>")
            open(outputFile, "a").write("<hr>")
    if args.histogram or args.ALL:
           get_histogram(logFile)
    if args.word_count or args.ALL:
           get_word_count(logFile)
    print("Analysis complete. Results are in " + outputFile)
    
    if filesWithNoErrors:
        if args.html:
            open(outputFile, "a").write("<h2 id=files-with-no-issues> Files with no issues </h2>")
            askForHelpHtml = """<p> Below list of files are shinier than my keyboard ⌨️ - no issues to report! If you do find something out of the ordinary ☠️ in them, <a href="https://github.com/yugabyte/yb-log-analyzer-py/issues/new?assignees=pgyogesh&labels=%23newmessage&template=add-new-message.md&title=%5BNew+Message%5D" target="_blank"> create a Github issue </a> and I'll put on my superhero 🦹‍♀️ cape to come to the rescue in future:\n </p>"""
            open(outputFile, "a").write(askForHelpHtml)
            open(outputFile, "a").write("<ul>")
            for file in filesWithNoErrors:
                open(outputFile, "a").write("<li>" + file + "</li>")
            open(outputFile, "a").write("</ul>")
        else:
            askForHelp = """\n\n Below list of files do not have any issues to report! If you do find something out of the ordinary in them, create a Github issue at:
            https://github.com/yugabyte/yb-log-analyzer-py/issues/new?assignees=pgyogesh&labels=%23newmessage&template=add-new-message.md&title=%5BNew+Message%5D\n\n"""
            open(outputFile, "a").write(askForHelp)
            for file in filesWithNoErrors:
                open(outputFile, "a").write('- ' + file + "\n")    
    