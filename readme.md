If you would like to test the interface on your laptop, first make sure that you have Node.js, Vite, and NPM installed in the frontend folder. Once those packages are verified and working, navigate into the frontend folder. Then, you can use `npm run dev` in your terminal to run the program.

To begin the live recording in fake-headset mode (as of 11/6/2026), open up a second terminal and navigate to ben-backend.
Then, run `python -m eeg_app.dashboard_service --fake-headset`.
To read the backend's saved-session summary and events, navigate into the frontend folder, then run these commands.
`
$base = "http://127.0.0.1:8765"
$id = "PASTE-SESSION-ID-HERE"

Invoke-RestMethod "$base/api/sessions/$id" |
  ConvertTo-Json -Depth 20

Invoke-RestMethod "$base/api/sessions/$id/events" |
  ConvertTo-Json -Depth 20
`
$base is the backend's base url as defined in api.ts. Make sure that the session ID is in quotes when you paste it. 