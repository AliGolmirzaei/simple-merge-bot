# simple merge bot

This project is a very simple GitLab merge robot. I developed it for a very special use case but I noticed how simple it was relative to my expectation when I started it. So I decided to make it open source to give a starting point and a bit of courage to anyone who needs to develop a GitLab bot.

# Why I developed this
1- In our company we were using Gitlab semi-linear merge history. This way whenever you want to merge, you need to have a linear history (there shouldn't be any commit on the target branch which is not in the source branch). So you always need to rebase your source branch before merging. Then after merging, git creates a merge commit on the destination branch for you. And there is a consequence. Your merge commit won't get into the source branch and then on the next merge you need to rebase the source branch. Then whoever has the source branch locally will get annoyed by the need of fixing their local branch history. And guess what, most developers are not git pros. They get confused on how to fix errors when they push/merge into develop branch. At first, my solution was to rebase the develop branch with master just after merging. But it was a burden! So I decided to have a bot carry my burden.

2- The next issue I faced was redundant CICD pipelines. Probably you are familiar with Gitlab "Auto-cancel redundant pipelines" setting. With this setting whenever you push multiple times to a branch older pipelines get canceled. But unfortunately, this won't work with triggered pipelines. What is the use case? We are using StrAPI and NextJs SSG (static site generation) to power our website and linked StrAPI webhook to our NextJs project pipeline trigger. So that when content changes the app will get built again having the latest content. Now if the content provider does multiple changes there would be many running pipelines in our NextJs project which are redundant. We cancel these redundant pipelines by the bot. The awesome part is, it is only 20 lines of code =)


# What it does
Just read the code from main function. As a reference:
* It monitors assignment of MRs and merge them
    * rebase the source branch if needed
    * wait for pipeline to succeed
    * rebase the source branch after merge
    * create a tag from master if requested
* cancel old pending and running pipelines which are on the same branch

# How to run it
* First create a user in your GitLab for the bot. 
* Then get the API token of the bot user. 
* Make bot as a maintainer of your project. 
* Set `GITLAB_URL` and `BOT_API_KEY` environment variable or edit the main.py and put them as `gitlabUrl` and `privateToken` respectively
* Run the bot with python3 main.py. I personally run it inside a docker container. If you are interested in how I do it I recommend you reading [my article](https://medium.com/@a.golmirzaei/how-to-automate-your-devops-using-gitlab-ci-cd-docker-ansible-part2-69257e1033e2)
* Enjoy!
