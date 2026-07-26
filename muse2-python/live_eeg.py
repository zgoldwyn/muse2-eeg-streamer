import subprocess

print("Looking for an EEG stream...")

process = subprocess.Popen("muse2-c/build/muse2_scan", stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)

while True:
    try:
        line = process.stdout.readline()
        if line.startswith("EEG,"):
            print(line)
            split_line = line.split(",")
            electrode = split_line[1]
            index = int(split_line[2])
            microvolts = float(split_line[3])
            print(f"Electrode: {electrode}, Index: {index}, Microvolts: {microvolts}\n")
    except KeyboardInterrupt:
        print("\nStopped.")
        process.terminate()
        break
    
