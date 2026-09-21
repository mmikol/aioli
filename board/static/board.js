/* The board's whole client: three small things a page cannot do for itself.

   Everything here is an improvement on something that already works. The
   forms are ordinary forms posting to ordinary routes, so with this file
   absent, blocked or broken the board still edits the pantry and answers a
   confirmation - it just reloads the page to do it. That is the order the
   backlog puts these in: the confirming has to cost almost nothing, and a
   view that only works once a script has arrived over a tailnet costs more
   than nothing on a kitchen phone.

   No framework and no CDN. Nothing is published and a CDN would be. */

(function () {
    "use strict";

    /* One listener each, on the document, so a swapped page needs no
       rebinding and nothing has to be torn down. */

    function swap(text) {
        /* The whole document comes back from a post, and only the main of it
           is new. Swapping that much keeps the scroll where it was, which on
           a list of confirmations is the difference between answering three
           meals and answering one. */
        var here = document.querySelector("main");
        var fresh = new DOMParser().parseFromString(text, "text/html")
            .querySelector("main");
        if (!here || !fresh) {
            return false;
        }
        here.innerHTML = fresh.innerHTML;
        grades();
        return true;
    }

    function sending(form, is) {
        form.querySelectorAll("button").forEach(function (button) {
            button.disabled = is;
        });
    }

    document.addEventListener("submit", function (event) {
        var form = event.target;
        if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") {
            return;
        }
        if (form.dataset.sending) {
            /* A second tap while the first is in the air. The cause in the
               form makes the duplicate harmless at the database; this only
               stops it being sent. */
            event.preventDefault();
            return;
        }
        var body = new FormData(form);
        var pressed = event.submitter;
        if (pressed && pressed.name) {
            /* Which button was pressed is half the message - finished and
               binned are the same form - and FormData does not carry the
               submitter in every browser that gets used here. */
            body.append(pressed.name, pressed.value);
        }
        event.preventDefault();
        form.dataset.sending = "1";
        sending(form, true);
        fetch(form.action, {
            method: "POST",
            body: new URLSearchParams(body),
            headers: {"Accept": "text/html"}
        }).then(function (answer) {
            if (!answer.ok) {
                throw new Error(answer.status);
            }
            return answer.text();
        }).then(function (text) {
            if (!swap(text)) {
                throw new Error("no main came back");
            }
        }).catch(function () {
            /* The tailnet dropped, or the board did. Hand the post back to
               the browser, which has an error page and a retry button and is
               better at both than this file would be. The pressed button
               rides along as a field, because a form submitted this way
               carries no submitter and the handler needs to know which one it
               was; posting twice is safe for the same reason the double tap
               above is. */
            delete form.dataset.sending;
            sending(form, false);
            if (pressed && pressed.name) {
                var carried = document.createElement("input");
                carried.type = "hidden";
                carried.name = pressed.name;
                carried.value = pressed.value;
                form.appendChild(carried);
            }
            form.submit();
        });
    });

    function grades() {
        /* A staple is in stock or it is not, and asking for its weight is the
           pantry nobody keeps. The fields are in the form either way so it
           works without this file; here they are put away when the grade
           being added does not measure. */
        document.querySelectorAll("form[data-add]").forEach(function (form) {
            var grade = form.querySelector("[name=grade]");
            if (!grade) {
                return;
            }
            form.querySelectorAll("[data-only]").forEach(function (part) {
                part.hidden = part.dataset.only !== grade.value;
            });
        });
    }

    document.addEventListener("change", function (event) {
        if (event.target && event.target.name === "grade") {
            grades();
        }
    });

    grades();
}());
