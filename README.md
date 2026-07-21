# <img src='./logo.svg' card_color="#FF8600" width="50" style="vertical-align:bottom" style="vertical-align:bottom">LLM Fallback  
  
## Summary
Get an LLM response from the Neon Diana backend.

## Description
Converse with an LLM and enable LLM responses when Neon doesn't have a better
response.

To send a single query to an LLM, you can ask Neon to "ask Chat GPT <something>".
To start conversing with an LLM, ask to "talk to Chat GPT" and have all of your input
sent to an LLM until you say goodbye or stop talking for a while.

Supported LLMs (subject to what your Neon Diana/Hana backend has deployed):
Chat GPT, FastChat, Claude, and Gemini. Name any of them in a request,
e.g. "ask Claude <something>" or "talk to Gemini".

Enable fallback behavior by asking to "enable LLM fallback skill" or disable it
by asking to "disable LLM fallback".

To have a copy of LLM interactions sent via email, ask Neon to 
"email me a copy of our conversation".

## Examples 

* "Explain quantum computing in simple terms"
* "Ask chat GPT what an LLM is"
* "Talk to chat GPT"
* "Enable LLM fallback skill"
* "Disable LLM fallback skill"
* "Email me a copy of our conversation"
